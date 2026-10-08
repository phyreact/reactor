#!/bin/sh
# Called by xiao_bridge_daemon.py:  $1 = wake | silence,  $2 = DOA in degrees (wake only, -1 if unknown)
# Runs as user radxa (no sudo). Put the ZERO's "wake up" / "go idle" actions here.
# stdout/stderr of this script are appended to ~/xiao-tools/wake.log.
EVENT=$1
DOA=$2

case "$EVENT" in
    wake)
        echo "hook: wake from ${DOA} deg -> (put start-the-app commands here)"
        # examples:
        #   systemctl --user start my-assistant.service
        #   curl -s http://127.0.0.1:8000/wake
        ;;
    silence)
        echo "hook: silence -> (put go-idle commands here)"
        # examples:
        #   systemctl --user stop my-assistant.service
        ;;
esac
