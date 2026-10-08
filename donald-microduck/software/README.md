# Radxa host tools

Python standard library; Linux needs ALSA `arecord` for capture.
Run the daemon as the user with access to the device's serial port:

```sh
python3 donald-microduck/software/xiao_bridge_daemon.py
python3 donald-microduck/software/cdc.py status
arecord -L
python3 donald-microduck/software/micscope.py --device YOUR_ALSA_DEVICE
```

Open `http://127.0.0.1:8778` on the host. For remote access, use an SSH tunnel;
`--bind` can explicitly select another interface. Captured audio is held in RAM;
the scope can export a WAV only when requested.

`on_wake.sh` receives `wake <direction>` and `silence` events. Add application
actions there. This package provides the audio/control tools; walking policies,
speech recognition and assistant services are separate integrations.

The daemon owns the CDC port. Other tools use its local Unix socket.
`XIAO_PORT_GLOB` selects the device; use an exact by-id path with multiple boards.
`XIAO_TOOLS_DIR` defaults to `~/xiao-tools`; `XIAO_WAKE_HOOK` overrides the hook.

For optional login/boot startup, copy these tools to `~/xiao-tools`,
install `xiao-bridge.service` under `~/.config/systemd/user/`, then run
`systemctl --user enable --now xiao-bridge`. The included udev rule prevents
ModemManager from claiming the CDC interface.
