#!/usr/bin/env python3
"""Stand-in for `arecord -D hw:1,0 -f S16_LE -r 16000 -c 2 -t raw -` on a machine
without ALSA: copies the virtual XIAO's audio socket (raw S16LE stereo 16 kHz) to
stdout.  micscope.py runs it via --capture-cmd when working against the twin.

    python3 sim_arecord.py [socket_path]      (default $XIAO_AUDIO_SOCK or sim/run/xiao_audio.sock)
"""
import os
import socket
import sys
import time

path = sys.argv[1] if len(sys.argv) > 1 else os.environ.get(
    "XIAO_AUDIO_SOCK", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "run", "xiao_audio.sock"))
out = os.fdopen(sys.stdout.fileno(), "wb", buffering=0)
while True:
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(path)
    except OSError as e:
        sys.stderr.write("sim_arecord: %s (%s), retrying\n" % (path, e))
        time.sleep(1.0)
        continue
    try:
        while True:
            data = s.recv(65536)
            if not data:
                break
            out.write(data)
    except (BrokenPipeError, OSError):
        break
    finally:
        s.close()
