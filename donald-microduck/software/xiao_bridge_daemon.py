#!/usr/bin/env python3
"""Single owner of the XIAO bridge's CDC control port on the ZERO.

- Opens /dev/serial/by-id/usb-*_XIAO_ReSpeaker_Audio_*-if03
  exclusively (TIOCEXCL) and reopens it whenever it disappears (XIAO reboot/flash).
- Unsolicited lines from the firmware, {"event":"wake","doa":N,...} and
  {"event":"silence",...}, are logged to ~/xiao-tools/wake.log and handed to
  ~/xiao-tools/on_wake.sh <event> <doa> (wake has a 2 s cooldown).
- UNIX socket ~/xiao-tools/cdc.sock: a client sends one command line and gets the
  reply lines back (connection closed after the reply). cdc.py and micscope.py
  use it, so nothing else fights over the serial port.

    python3 xiao_bridge_daemon.py            (foreground; see xiao-bridge.service)
"""
import glob, json, os, select, socket, subprocess, sys, termios, threading, time, tty, fcntl

USER_DIRECTORY = os.path.expanduser("~")
# Environment overrides let the same daemon run against the software twin
# (sim/run_sim.py) on a machine without the hardware.
TOOLS = os.environ.get("XIAO_TOOLS_DIR", os.path.join(USER_DIRECTORY, "xiao-tools"))
SOCK = os.path.join(TOOLS, "cdc.sock")
HOOK = os.environ.get("XIAO_WAKE_HOOK") or (
    os.path.join(TOOLS, "on_wake.sh") if os.path.exists(os.path.join(TOOLS, "on_wake.sh"))
    else os.path.join(os.path.dirname(os.path.abspath(__file__)), "on_wake.sh"))
LOG = os.path.join(TOOLS, "wake.log")
PORT_GLOB = os.environ.get("XIAO_PORT_GLOB", "/dev/serial/by-id/usb-*_XIAO_ReSpeaker_Audio_*-if03")
WAKE_COOLDOWN = 2.0


def log(msg):
    line = "%s %s" % (time.strftime("%F %T"), msg)
    print(line, flush=True)
    try:
        with open(LOG, "a") as f:
            f.write(line + "\n")
    except OSError:
        pass


class Bridge:
    def __init__(self):
        self.fd = None
        self.port = None
        self.req_lock = threading.Lock()       # one command in flight at a time
        self.reply_lines = []
        self.reply_cv = threading.Condition()
        self.last_wake = 0.0
        self.events = 0

    # ---- serial -------------------------------------------------------------
    def open_port(self):
        ports = glob.glob(PORT_GLOB)
        if not ports:
            return False
        try:
            fd = os.open(ports[0], os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
            tty.setraw(fd)
            a = termios.tcgetattr(fd); a[2] &= ~termios.HUPCL; termios.tcsetattr(fd, termios.TCSANOW, a)
            fcntl.ioctl(fd, termios.TIOCEXCL)
        except OSError as e:
            log("open %s failed: %s" % (ports[0], e))
            return False
        # Events the firmware queued while nobody was reading arrive in a burst
        # right after open; flush them and treat anything in the first 1.5 s as stale.
        time.sleep(0.3)
        try: termios.tcflush(fd, termios.TCIFLUSH)
        except OSError: pass
        self.opened_at = time.time()
        self.fd, self.port = fd, ports[0]
        log("port open: %s" % ports[0])
        return True

    def close_port(self):
        if self.fd is not None:
            try: os.close(self.fd)
            except OSError: pass
        self.fd = None
        self.port = None

    def reader(self):
        buf = b""
        while True:
            if self.fd is None:
                if not self.open_port():
                    time.sleep(1.0)
                    continue
                buf = b""
            try:
                r, _, _ = select.select([self.fd], [], [], 1.0)
                if not r:
                    continue
                chunk = os.read(self.fd, 4096)
            except OSError as e:
                log("port lost: %s" % e)
                self.close_port()
                time.sleep(0.5)
                continue
            if not chunk:
                continue
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                self.handle_line(line.decode(errors="replace").strip())

    def handle_line(self, line):
        if not line:
            return
        if line.startswith('{"event"'):
            self.dispatch_event(line)
            return
        with self.reply_cv:
            self.reply_lines.append(line)
            self.reply_cv.notify_all()

    # ---- events -------------------------------------------------------------
    def dispatch_event(self, line):
        try:
            ev = json.loads(line)
        except ValueError:
            log("bad event line: %r" % line)
            return
        name = str(ev.get("event"))
        doa = ev.get("doa", -1)
        self.events += 1
        now = time.time()
        if now - getattr(self, "opened_at", 0) < 1.5:
            log("stale event after port open ignored: %s" % line)
            return
        if name == "wake" and now - self.last_wake < WAKE_COOLDOWN:
            log("event wake (doa %s) suppressed by cooldown" % doa)
            return
        if name == "wake":
            self.last_wake = now
        log("event %s doa=%s uptime_ms=%s" % (name, doa, ev.get("uptime_ms")))
        if os.path.exists(HOOK):
            try:
                subprocess.Popen(["/bin/sh", HOOK, name, str(doa)], stdin=subprocess.DEVNULL,
                                 stdout=open(LOG, "a"), stderr=subprocess.STDOUT)
            except OSError as e:
                log("hook failed: %s" % e)

    # ---- command broker -----------------------------------------------------
    def command(self, cmd, timeout=2.5):
        with self.req_lock:
            if self.fd is None:
                return '{"error":"XIAO port not open"}\n'
            with self.reply_cv:
                self.reply_lines = []
            try:
                os.write(self.fd, (cmd + "\n").encode())
            except OSError as e:
                return '{"error":"write: %s"}\n' % e
            deadline = time.time() + timeout
            got = []
            multi = cmd.strip() == "log"
            with self.reply_cv:
                while time.time() < deadline:
                    if self.reply_lines:
                        got.extend(self.reply_lines); self.reply_lines = []
                        if not multi or any('"log_end"' in l for l in got):
                            break
                    self.reply_cv.wait(0.05)
            return "".join(l + "\n" for l in got) if got else '{"error":"no reply"}\n'

    def serve(self):
        try: os.unlink(SOCK)
        except FileNotFoundError: pass
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(SOCK); os.chmod(SOCK, 0o600); srv.listen(8)
        log("socket ready: %s" % SOCK)
        while True:
            conn, _ = srv.accept()
            threading.Thread(target=self.client, args=(conn,), daemon=True).start()

    def client(self, conn):
        with conn:
            conn.settimeout(5.0)
            try:
                data = b""
                while b"\n" not in data:
                    chunk = conn.recv(1024)
                    if not chunk: break
                    data += chunk
                cmd = data.split(b"\n", 1)[0].decode(errors="replace").strip()
                if cmd:
                    conn.sendall(self.command(cmd).encode())
            except (OSError, socket.timeout):
                pass


def main():
    os.makedirs(TOOLS, exist_ok=True)
    b = Bridge()
    threading.Thread(target=b.reader, daemon=True).start()
    try:
        b.serve()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
