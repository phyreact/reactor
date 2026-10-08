import ctypes
import importlib.util
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("box_host", ROOT / "zero/box_host.py")
host = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = host
spec.loader.exec_module(host)
sys.path.insert(0, str(ROOT / "zero"))
from box_peripherals import Fan


class CPacket(ctypes.Structure):
    _fields_ = [("kind", ctypes.c_uint8), ("length", ctypes.c_uint8),
                ("sequence", ctypes.c_uint16), ("session", ctypes.c_uint32),
                ("payload", ctypes.c_uint8 * 50)]


def status(seq=1, command_seq=0, session=123, accepted=False, ok=True, shutdown=0, token=0):
    payload = bytearray(24)
    payload[0] = payload[1] = 1
    struct.pack_into("<I", payload, 8, token)
    payload[12] = shutdown
    struct.pack_into("<H", payload, 20, command_seq)
    payload[22], payload[23] = accepted, ok
    return host.Packet(host.HOST_STATUS, seq, session, payload)


class FakeTransport:
    def __init__(self, reject=False, changed=False):
        self.pending = status(command_seq=65535, accepted=True).encode()
        self.writes = []
        self.reject, self.changed = reject, changed

    def read(self, _):
        value, self.pending = self.pending, b""
        return value

    def write(self, raw):
        packet = host.Packet.decode(raw)
        self.writes.append(packet)
        self.pending += status(seq=2, session=124 if self.changed else 123,
                               command_seq=packet.sequence, accepted=True,
                               ok=not self.reject).encode()


class Tests(unittest.TestCase):
    def test_c_python_wire_interoperability(self):
        library = ctypes.CDLL(os.environ["BOX_PROTOCOL_LIBRARY"])
        library.box_encode.argtypes = [ctypes.POINTER(CPacket), ctypes.POINTER(ctypes.c_uint8)]
        library.box_decode.argtypes = [ctypes.POINTER(ctypes.c_uint8), ctypes.POINTER(CPacket)]
        library.box_decode.restype = ctypes.c_bool
        for length in (0, 5, 24, 37, 48, 50):
            for sequence in (0, 65535):
                payload = bytes(range(length))
                c = CPacket(3, length, sequence, 0xF1234567)
                c.payload[:length] = payload
                raw = (ctypes.c_uint8 * 64)()
                library.box_encode(ctypes.byref(c), raw)
                p = host.Packet(3, sequence, c.session, payload)
                self.assertEqual(bytes(raw), p.encode())
                self.assertEqual(host.Packet.decode(bytes(raw)), p)
                out = CPacket()
                self.assertTrue(library.box_decode(raw, ctypes.byref(out)))
                self.assertEqual(bytes(out.payload[:out.length]), payload)

    def test_stream_corruption_and_truncation(self):
        p = status()
        raw = p.encode()
        parser = host.Parser()
        got = []
        stream = b"noise\xa5" + raw[:22] + raw + bytes([raw[0] ^ 1]) + raw[1:] + raw
        for i in range(0, len(stream), 3):
            got += parser.feed(stream[i:i + 3])
        self.assertEqual(got, [p, p])
        for bit in range(512):
            corrupt = bytearray(raw)
            corrupt[bit // 8] ^= 1 << (bit % 8)
            with self.assertRaises(ValueError):
                host.Packet.decode(corrupt)

    def test_command_sequence_wrap_and_ack(self):
        transport = FakeTransport()
        link = host.Link(transport)
        result = link.command(host.RADAR_SET, 1)
        self.assertEqual(result["command_sequence"], 0)
        self.assertEqual(transport.writes[0].payload, struct.pack("<BI", host.RADAR_SET, 1))
        self.assertEqual(transport.writes[0].session, 123)

    def test_reject_and_session_change(self):
        for transport in (FakeTransport(reject=True), FakeTransport(changed=True)):
            with self.assertRaises(RuntimeError):
                host.Link(transport).command(host.ALL_OFF)
            self.assertEqual(len(transport.writes), 1)

    def test_old_status_cannot_undo_ack(self):
        transport = FakeTransport()
        link = host.Link(transport)
        link.command(host.TOF_SET)
        transport.pending = status(seq=1).encode()
        link.poll()
        self.assertEqual(link.status["sequence"], 2)

    def test_storage_guard(self):
        ro = "24 1 179:2 / / ro,relatime - ext4 /dev/mmcblk0p2 ro\n"
        volatile = "25 24 0:4 / /run rw,nosuid - tmpfs tmpfs rw\n"
        swap_header = "Filename Type Size Used Priority\n"
        self.assertTrue(host.storage_quiescent(ro + volatile, swap_header))
        self.assertFalse(host.storage_quiescent(ro.replace("ro", "rw"), swap_header))
        self.assertFalse(host.storage_quiescent(ro + "26 24 8:1 / /data rw - ext4 /dev/sda1 rw\n", swap_header))
        self.assertFalse(host.storage_quiescent(ro, swap_header + "/swap file 100 20 -2\n"))
        self.assertFalse(host.storage_quiescent("", swap_header))
        self.assertFalse(host.storage_quiescent("broken", swap_header))
        self.assertFalse(host.storage_quiescent(ro.replace("mmcblk0p2 ro", "mmcblk0p2 rw"), swap_header))

    def test_hook_rejects_ordinary_execution_and_non_poweroff(self):
        with patch.object(host, "Serial") as serial, patch.object(host, "shutdown_ancestor", return_value=False):
            for action in ("reboot", "halt", "kexec"):
                self.assertEqual(host.final_poweroff(action, {"poweroff_enabled": True}), 0)
            self.assertEqual(host.final_poweroff("poweroff", {"poweroff_enabled": False}), 0)
            with self.assertRaises(RuntimeError):
                host.final_poweroff("poweroff", {"poweroff_enabled": True})
            serial.assert_not_called()

    def test_hook_refuses_writable_storage(self):
        with patch.object(host, "shutdown_ancestor", return_value=True), \
             patch.object(Path, "read_text", return_value="invalid"), \
             patch.object(host, "Serial") as serial:
            with self.assertRaises(RuntimeError):
                host.final_poweroff("poweroff", {"poweroff_enabled": True})
            serial.assert_not_called()

    def test_cut_ack_not_exposed_to_live_daemon(self):
        with self.assertRaises(ValueError):
            host.request_command(None, None, {"command": "safe-to-cut", "token": 123})

    def test_late_hook_uses_current_pending_token(self):
        ro = "24 1 179:2 / / ro - ext4 /dev/mmcblk0p2 ro\n"
        with patch.object(host, "shutdown_ancestor", return_value=True), \
             patch.object(Path, "read_text", side_effect=[ro, "Filename Type Size Used Priority\n"]), \
             patch.object(host, "Serial") as serial, patch.object(host, "Link") as link:
            link.return_value.wait_status.return_value = {
                "host_on": True, "shutdown": 2, "shutdown_token": 0x12345678}
            host.final_poweroff("poweroff", {"poweroff_enabled": True, "uart": "/dev/mock"})
            link.return_value.command.assert_called_once_with(host.SAFE_TO_CUT, 0x12345678)
            serial.return_value.close.assert_called_once()

    def test_fan_inversion(self):
        with tempfile.TemporaryDirectory() as directory:
            fan = Fan(directory, {"electrical_qualified": True})
            for duty, phase in ((100, 0), (75, 10000), (0, 40000)):
                fan.set(duty)
                self.assertEqual((Path(directory) / "duty_cycle").read_text(), str(phase))
                self.assertEqual((Path(directory) / "period").read_text(), "40000")
            with self.assertRaises(ValueError):
                fan.set(101)


if __name__ == "__main__":
    unittest.main(verbosity=2)
