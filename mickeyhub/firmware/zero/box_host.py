#!/usr/bin/python3
"""R2.1R ZERO UART9 supervisor and late systemd poweroff hook; standard library only."""
import argparse
import binascii
import dataclasses
import fcntl
import json
import os
from pathlib import Path
import select
import signal
import socket
import struct
import subprocess
import sys
import termios
import time
import tty

FRAME_SIZE = 64
HOST_COMMAND, HOST_STATUS, RADAR_SAMPLE = 3, 4, 5
READY, HOST_ON, HOST_OFF, ALL_OFF, RADAR_SET, TOF_SET, SAFE_TO_CUT, GET_STATUS = range(1, 9)
CONFIG = "/etc/box-controller.json"
SOCKET = "/run/box-controller/control.sock"


@dataclasses.dataclass
class Packet:
    kind: int
    sequence: int
    session: int
    payload: bytes

    def encode(self):
        if not 1 <= self.kind <= 5 or len(self.payload) > 50:
            raise ValueError("Invalid packet")
        frame = bytearray(64)
        struct.pack_into("<BBBBHBBI", frame, 0, 0xA5, 0x5A, 1, self.kind,
                         self.sequence, len(self.payload), 0, self.session)
        frame[12:12 + len(self.payload)] = self.payload
        struct.pack_into("<H", frame, 62, binascii.crc_hqx(frame[:62], 0xFFFF))
        return bytes(frame)

    @staticmethod
    def decode(frame):
        if (len(frame) != 64 or frame[:3] != b"\xa5\x5a\x01" or
                not 1 <= frame[3] <= 5 or frame[6] > 50 or frame[7] or
                binascii.crc_hqx(frame[:62], 0xFFFF) != struct.unpack_from("<H", frame, 62)[0]):
            raise ValueError("Invalid frame / CRC")
        return Packet(frame[3], struct.unpack_from("<H", frame, 4)[0],
                      struct.unpack_from("<I", frame, 8)[0], frame[12:12 + frame[6]])


class Parser:
    def __init__(self):
        self.data = bytearray()

    def feed(self, data):
        self.data.extend(data)
        packets = []
        while True:
            at = self.data.find(b"\xa5\x5a")
            if at < 0:
                self.data[:] = self.data[-1:] if self.data[-1:] == b"\xa5" else b""
                break
            del self.data[:at]
            if len(self.data) < 64:
                break
            try:
                packets.append(Packet.decode(self.data[:64]))
                del self.data[:64]
            except ValueError:
                del self.data[0]
        return packets


def decode_status(p):
    if p.kind != HOST_STATUS or len(p.payload) < 24 or not p.session:
        raise ValueError("Not a complete RP status")
    b = p.payload
    if (any(b[i] > 1 for i in (0, 1, 2, 13, 14, 22, 23)) or b[3] > 5 or b[12] > 2):
        raise ValueError("Invalid RP state fields")
    return {"session": p.session, "sequence": p.sequence,
            "host_on": bool(b[0]), "main_hold": bool(b[1]), "tof_on": bool(b[2]),
            "radar_phase": b[3], "faults": struct.unpack_from("<I", b, 4)[0],
            "shutdown_token": struct.unpack_from("<I", b, 8)[0], "shutdown": b[12],
            "safe_received": bool(b[13]), "radar_tx_released": bool(b[14]),
            "cycle": struct.unpack_from("<I", b, 16)[0],
            "command_sequence": struct.unpack_from("<H", b, 20)[0],
            "command_seen": bool(b[22]), "command_ok": bool(b[23])}


def newer(a, b):
    return 0 < ((a - b) & 0xFFFF) < 0x8000


class Serial:
    def __init__(self, device):
        self.fd = os.open(device, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            tty.setraw(self.fd, termios.TCSANOW)
            attrs = termios.tcgetattr(self.fd)
            attrs[2] = (attrs[2] & ~(termios.PARENB | termios.CSTOPB | termios.CSIZE |
                                   getattr(termios, "CRTSCTS", 0))) | termios.CS8 | termios.CLOCAL | termios.CREAD
            attrs[4] = attrs[5] = termios.B115200
            termios.tcsetattr(self.fd, termios.TCSANOW, attrs)
            termios.tcflush(self.fd, termios.TCIOFLUSH)
        except Exception:
            os.close(self.fd)
            raise

    def read(self, timeout):
        if not select.select([self.fd], [], [], timeout)[0]:
            return b""
        data = os.read(self.fd, 4096)
        if not data:
            raise OSError("UART closed")
        return data

    def write(self, data):
        deadline = time.monotonic() + 0.5
        while data:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([], [self.fd], [], remaining)[1]:
                raise TimeoutError("UART write timeout")
            count = os.write(self.fd, data)
            data = data[count:]

    def close(self):
        os.close(self.fd)


class Link:
    def __init__(self, transport):
        self.transport = transport
        self.parser = Parser()
        self.status = None
        self.received_at = 0
        self.radar = {}

    def poll(self, timeout=0.1):
        for p in self.parser.feed(self.transport.read(timeout)):
            if p.kind == HOST_STATUS:
                try:
                    status = decode_status(p)
                except ValueError:
                    continue
                # A long outage may exceed half the 16-bit sequence space.
                if (self.status and self.status["session"] == p.session and
                        time.monotonic() - self.received_at < 1.5 and
                        not newer(p.sequence, self.status["sequence"])):
                    continue
                self.status, self.received_at = status, time.monotonic()
            elif p.kind == RADAR_SAMPLE and len(p.payload) == 37:
                if not self.status or p.session != self.status["session"]:
                    continue
                idx = p.payload[0]
                if idx < 4 and p.payload[7:11] == b"\xaa\xff\x03\x00" and p.payload[-2:] == b"\x55\xcc":
                    self.radar[idx] = {"raw_hex": p.payload[7:].hex(),
                                       "received_at_monotonic": time.monotonic()}

    def wait_status(self, timeout=2):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.poll(min(0.1, max(0, deadline - time.monotonic())))
            if self.status and time.monotonic() - self.received_at < 0.5:
                return self.status
        raise TimeoutError("No fresh RP status; power remains unchanged")

    def command(self, command, value=0, timeout=2):
        status = self.wait_status(timeout)
        session = status["session"]
        sequence = ((status["command_sequence"] if status["command_seen"] else 0) + 1) & 0xFFFF
        packet = Packet(HOST_COMMAND, sequence, session, struct.pack("<BI", command, value))
        self.transport.write(packet.encode())
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.poll(0.05)
            status = self.status
            if status["session"] != session:
                raise RuntimeError("RP session changed; command needs a new request")
            if status["command_seen"] and status["command_sequence"] == sequence:
                if not status["command_ok"]:
                    raise RuntimeError("RP rejected command")
                return status
        # Do not retry power-changing requests blindly after an ambiguous ACK.
        raise TimeoutError("RP command acknowledgement timeout")


VOLATILE_FS = {"proc", "sysfs", "tmpfs", "devtmpfs", "devpts", "cgroup", "cgroup2",
               "securityfs", "debugfs", "tracefs", "pstore", "configfs", "fusectl",
               "bpf", "mqueue", "hugetlbfs", "ramfs", "autofs"}


def storage_quiescent(mountinfo, swaps):
    """Fail closed if any persistent filesystem is still writable or swap is active."""
    root_readonly = False
    for line in mountinfo.splitlines():
        fields = line.split()
        if "-" not in fields or len(fields) < 10:
            return False
        separator = fields.index("-")
        if separator + 3 >= len(fields):
            return False
        mountpoint, options = fields[4], fields[5].split(",")
        filesystem = fields[separator + 1]
        super_options = fields[separator + 3].split(",")
        if mountpoint == "/" and "ro" in options:
            root_readonly = True
        if filesystem not in VOLATILE_FS and ("ro" not in options or "ro" not in super_options):
            return False
    return root_readonly and len([s for s in swaps.splitlines() if s.strip()]) <= 1


def shutdown_ancestor():
    pid = os.getppid()
    for _ in range(8):
        try:
            executable = os.path.basename(os.readlink(f"/proc/{pid}/exe"))
            if executable == "systemd-shutdown":
                return True
            text = Path(f"/proc/{pid}/stat").read_text()
            pid = int(text[text.rfind(")") + 2:].split()[1])
        except (OSError, ValueError, IndexError):
            return False
        if pid <= 0:
            break
    return False


def final_poweroff(action, config):
    if action != "poweroff" or not config.get("poweroff_enabled", False):
        return 0
    if not shutdown_ancestor():
        raise RuntimeError("Late acknowledgement requires systemd-shutdown ancestry")
    if not storage_quiescent(Path("/proc/self/mountinfo").read_text(),
                             Path("/proc/swaps").read_text()):
        raise RuntimeError("Storage is not quiescent; retaining HOST power")
    transport = Serial(config["uart"])
    try:
        link = Link(transport)
        status = link.wait_status()
        if not status["host_on"]:
            return 0
        if not status["shutdown"]:
            status = link.command(HOST_OFF)
        token = status["shutdown_token"]
        if not token:
            raise RuntimeError("No pending shutdown token")
        link.command(SAFE_TO_CUT, token)
        # This authorizes cut after late storage shutdown, not a claim that the
        # CPU has already halted. RP additionally waits for the radar-off ACK.
        return 0
    finally:
        transport.close()


def request_command(link, fan, request, tof=None):
    action = request.get("command")
    if action == "status":
        return {"power": link.wait_status(), "radar": link.radar,
                "fan": fan.status(), "tof": tof.status() if tof else None}
    if action in ("tof-on", "tof-off"):
        if tof is None:
            raise RuntimeError("VL53L8CX driver not configured; legacy M17 control is disabled")
        status = link.wait_status()
        if action == "tof-on" and (not status["host_on"] or status["shutdown"]):
            raise RuntimeError("ToF cannot start during shutdown")
        return tof.start() if action == "tof-on" else tof.stop()
    commands = {"host-off": (HOST_OFF, 0), "all-off": (ALL_OFF, 0),
                "radar-on": (RADAR_SET, 1), "radar-off": (RADAR_SET, 0)}
    if action in commands:
        tof_error = None
        if action in ("host-off", "all-off") and tof:
            try:
                tof.stop()
            except (RuntimeError, OSError) as exc:
                tof_error = str(exc)
        result = link.command(*commands[action])
        if tof_error:
            result = {**result, "tof_stop_error": tof_error}
        return result
    if action == "fan":
        fan.set(float(request["duty"]))
        return {"fan_duty": float(request["duty"])}
    raise ValueError("Unknown command (late-cut ACK is deliberately not exposed)")


def daemon(config):
    # Late shutdown hook deliberately does not import optional peripherals.
    from box_peripherals import Fan, ToF
    transport = Serial(config["uart"])
    link = Link(transport)
    fan = Fan(config.get("fan_pwm_channel"), config.get("fan"))
    tof = ToF(config.get("tof"))
    address = config.get("socket", SOCKET)
    Path(address).parent.mkdir(parents=True, exist_ok=True)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    if os.path.exists(address):
        os.unlink(address)
    server.bind(address)
    os.chmod(address, 0o600)
    server.listen(4)
    server.setblocking(False)
    stopping = False

    def stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    ready_session = None
    shutdown_attempt = None
    shutdown_retry_at = 0
    try:
        fan.start()
        while not stopping:
            link.poll(0.1)
            for peripheral in (fan, tof):
                try:
                    peripheral.poll()
                except (OSError, RuntimeError, ValueError) as exc:
                    print(f"Peripheral error: {exc}", file=sys.stderr, flush=True)
            status = link.status
            if status and time.monotonic() - link.received_at < 0.5:
                if status["host_on"] and not status["shutdown"] and ready_session != status["session"]:
                    try:
                        link.command(READY)
                        ready_session = status["session"]
                    except (TimeoutError, RuntimeError) as exc:
                        print(str(exc), file=sys.stderr, flush=True)
                pending = (status["session"], status["shutdown_token"])
                if (status["host_on"] and status["shutdown"] and status["shutdown_token"] and
                        pending != shutdown_attempt and time.monotonic() >= shutdown_retry_at):
                    # A failed I2C stop must not indefinitely prevent an orderly
                    # OS shutdown. ToF and its pullups lose their shared rail
                    # together when HOST is finally released.
                    try:
                        tof.stop()
                    except (RuntimeError, OSError) as exc:
                        print(str(exc), file=sys.stderr, flush=True)
                    if config.get("poweroff_enabled", False):
                        try:
                            result = subprocess.run(["/usr/bin/systemctl", "poweroff"],
                                                    timeout=10, check=False)
                        except (OSError, subprocess.TimeoutExpired) as exc:
                            print(f"Poweroff request failed: {exc}", file=sys.stderr, flush=True)
                            shutdown_retry_at = time.monotonic() + 5
                        else:
                            if result.returncode == 0:
                                shutdown_attempt = pending
                            else:
                                shutdown_retry_at = time.monotonic() + 5
                    else:
                        print("Commissioning mode: poweroff request observed, no OS shutdown",
                              file=sys.stderr, flush=True)
                        shutdown_attempt = pending
            if not select.select([server], [], [], 0)[0]:
                continue
            client, _ = server.accept()
            with client:
                client.settimeout(1)
                try:
                    raw = bytearray()
                    while b"\n" not in raw and len(raw) <= 2048:
                        part = client.recv(2048)
                        if not part:
                            break
                        raw.extend(part)
                    if len(raw) > 2048 or b"\n" not in raw:
                        raise ValueError("Request must be one JSON line, <=2048 bytes")
                    result = {"ok": True, "result": request_command(link, fan, json.loads(raw.split(b"\n")[0]), tof)}
                except (ValueError, OSError, RuntimeError, TimeoutError) as exc:
                    result = {"ok": False, "error": str(exc)}
                try:
                    client.sendall((json.dumps(result) + "\n").encode())
                except OSError:
                    pass
    finally:
        for device in (tof, fan):
            try:
                device.close()
            except (OSError, RuntimeError) as exc:
                print(f"Peripheral close failed: {exc}", file=sys.stderr)
        server.close()
        os.unlink(address)
        transport.close()


def main():
    if len(sys.argv) == 2 and sys.argv[1] in ("poweroff", "halt", "reboot", "kexec"):
        if sys.argv[1] != "poweroff":
            return 0
        return final_poweroff(sys.argv[1], json.loads(Path(CONFIG).read_text()))
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=CONFIG)
    parser.add_argument("mode", choices=["daemon", "status", "host-off", "all-off", "radar-on",
                                        "radar-off", "tof-on", "tof-off", "fan"])
    parser.add_argument("--duty", type=float, default=100)
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text())
    if args.mode == "daemon":
        return daemon(config)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(5)
        client.connect(config.get("socket", SOCKET))
        client.sendall((json.dumps({"command": args.mode, "duty": args.duty}) + "\n").encode())
        data = bytearray()
        while b"\n" not in data and len(data) < 32768:
            part = client.recv(4096)
            if not part:
                break
            data.extend(part)
        result = json.loads(data)
        print(json.dumps(result, indent=2))
        return 0 if result["ok"] else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, RuntimeError, TimeoutError) as error:
        print(f"box-controller: {error}", file=sys.stderr)
        sys.exit(1)
