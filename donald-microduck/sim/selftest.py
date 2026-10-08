#!/usr/bin/env python3
"""Exercise the simulated audio/CDC chain with the actual host tools."""
import csv
import json
import os
from pathlib import Path
import shlex
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

DUCK = Path(__file__).resolve().parents[1]


def wait_for(predicate, timeout=12):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.1)
    raise TimeoutError("simulation service did not become ready")


def main():
    processes, logs = [], []
    # Keep Unix socket paths below platform length limits, even on macOS.
    with tempfile.TemporaryDirectory(prefix="reactor-", dir="/tmp") as temporary:
        run = Path(temporary)
        env = dict(os.environ, XIAO_TOOLS_DIR=str(run / "tools"),
                   XIAO_PORT_GLOB=str(run / "dev/serial/by-id/*"),
                   XIAO_AUDIO_SOCK=str(run / "xiao_audio.sock"))

        def start(script, *args):
            log = open(run / (Path(script).stem + ".log"), "w+")
            logs.append(log)
            process = subprocess.Popen([sys.executable, script, *args], cwd=DUCK,
                                       env=env, stdout=log, stderr=log, start_new_session=True)
            processes.append(process)
            return process

        def command(value):
            result = subprocess.run(
                [sys.executable, "software/cdc.py", value, "1"],
                cwd=DUCK, env=env, text=True, capture_output=True, timeout=6, check=True)
            replies = [json.loads(line) for line in result.stdout.splitlines() if line.startswith("{")]
            assert replies, result.stdout
            return replies[-1]

        try:
            sim = start("sim/run_sim.py", "--run-dir", str(run), "--duration", "35", "--quiet")
            wait_for(lambda: (run / "xiao_audio.sock").exists())
            start("software/xiao_bridge_daemon.py")
            wait_for(lambda: (run / "tools/cdc.sock").exists())
            time.sleep(.6)
            assert command("ping")["reply"] == "pong"
            assert command("vad_silence 3000")["ok"]
            version = command("i2c_read 308004 4")
            assert version.get("rx") == "00010008", version
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as audio:
                audio.settimeout(3)
                audio.connect(str(run / "xiao_audio.sock"))
                captured = bytearray()
                while len(captured) < 32000:
                    chunk = audio.recv(8192)
                    if not chunk:
                        raise RuntimeError("audio stream ended early")
                    captured.extend(chunk)
                assert any(captured), "audio contains only zeros"
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                port = probe.getsockname()[1]
            start("software/micscope.py", "--port", str(port), "--capture-cmd",
                  shlex.join([sys.executable, "sim/twin/sim_arecord.py"]))

            def scope_ready():
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1) as response:
                        return response.status == 200
                except OSError:
                    return False

            wait_for(scope_ready)
            assert sim.wait(timeout=45) == 0
            time.sleep(.3)
            wake_log = (run / "tools/wake.log").read_text()
            assert wake_log.count("event wake ") == 3, wake_log
            assert wake_log.count("event silence ") == 3, wake_log
            with (run / "doa_log.csv").open() as stream:
                rows = list(csv.DictReader(stream))
            speech = [r for r in rows if r["truth_speech"] == "1" and r["est_az"]]
            valid = [r for r in speech if r["est_valid"] == "1"]
            assert len(valid) > .8 * len(speech), "too few valid directions"
            errors = sorted(abs((float(r["est_az"]) - float(r["truth_az"]) + 180) % 360 - 180)
                            for r in valid)
            median = errors[len(errors) // 2]
            assert median < 5, errors[:10]
            print(f"PASS: CDC, I2C, audio, scope, 3 wake events; median direction error {median:.2f}°")
        except Exception:
            for log in logs:
                log.flush()
                log.seek(0)
                print(Path(log.name).name, log.read()[-2500:], file=sys.stderr)
            raise
        finally:
            for process in reversed(processes):
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            for process in processes:
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
            for log in logs:
                log.close()


if __name__ == "__main__":
    main()
