# Audio/control simulation

Use Python 3.12 or later, from the repository root:

```sh
python3 -m venv .venv
.venv/bin/pip install -r donald-microduck/sim/requirements.txt
.venv/bin/python donald-microduck/sim/selftest.py
```

The test runs the MuJoCo robot, acoustic propagation, XVF3800/XIAO behavioural
models and actual host tools. It checks CDC, I2C, nonzero audio, the scope,
three wake events and sound direction. It uses synthetic broadband sound;
no microphone, camera, network account or recorded voice is needed.

For interactive use, run `cd donald-microduck`, then:

```sh
python3 sim/run_sim.py
```

In another terminal, also inside `donald-microduck/`:

```sh
export XIAO_TOOLS_DIR="$PWD/sim/run/tools"
export XIAO_PORT_GLOB="$PWD/sim/run/dev/serial/by-id/*"
export XIAO_AUDIO_SOCK="$PWD/sim/run/xiao_audio.sock"
python3 software/xiao_bridge_daemon.py
```

The virtual DSP uses free-field propagation, direction estimation, energy VAD
and delay-and-sum beamforming. It does not reproduce the proprietary XMOS DSP,
room reflections, USB timing or hardware reliability. Array direction in the
simulation is explicitly defined; real hardware still needs calibration.
