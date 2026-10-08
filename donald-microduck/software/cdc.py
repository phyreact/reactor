#!/usr/bin/env python3
"""cdc.py <command> [wait_s] : send one line to the XIAO bridge, print the reply.

Goes through the bridge daemon's socket (~/xiao-tools/cdc.sock) when it is
running, otherwise opens the CDC port directly (fails with EBUSY while the
daemon holds it exclusively).
"""
import glob, os, socket, sys, termios, time, tty

TOOLS = os.environ.get("XIAO_TOOLS_DIR", os.path.expanduser("~/xiao-tools"))
SOCK = os.path.join(TOOLS, "cdc.sock")
PORT_GLOB = os.environ.get("XIAO_PORT_GLOB", "/dev/serial/by-id/usb-*_XIAO_ReSpeaker_Audio_*-if03")
cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
wait = float(sys.argv[2]) if len(sys.argv) > 2 else 0.6

if os.path.exists(SOCK):
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(wait + 3.0)
        s.connect(SOCK)
        s.sendall((cmd + "\n").encode())
        buf = b""
        while True:
            chunk = s.recv(4096)
            if not chunk: break
            buf += chunk
    print(buf.decode(errors="replace").strip())
    sys.exit(0)

ports = glob.glob(PORT_GLOB)
if not ports:
    sys.exit("no XIAO bridge CDC port")
fd = os.open(ports[0], os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK); tty.setraw(fd)
a = termios.tcgetattr(fd); a[2] &= ~termios.HUPCL; termios.tcsetattr(fd, termios.TCSANOW, a)
os.write(fd, (cmd + "\n").encode()); buf = b""; t = time.time() + wait
while time.time() < t:
    try: buf += os.read(fd, 4096)
    except BlockingIOError: time.sleep(0.02)
print(buf.decode(errors="replace").strip())
