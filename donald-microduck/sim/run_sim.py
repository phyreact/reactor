#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Run the whole software-only rig: MuJoCo duck + acoustics -> virtual XVF3800 -> virtual XIAO.

    .venv/bin/python sim/run_sim.py [--scenario sim/scenarios/default.json] [--pose hat|spider]
                                    [--xmos i2s|usb] [--dynamic] [--speed 1.0] [--duration S]
                                    [--run-dir sim/run] [--quiet]

While it runs, the ZERO-side software talks to the twin exactly as to the hardware:
    export XIAO_PORT_GLOB="$PWD/sim/run/dev/serial/by-id/usb-*_XIAO_ReSpeaker_Audio_*-if03"
    export XIAO_TOOLS_DIR="$PWD/sim/run/tools"
    python3 software/xiao_bridge_daemon.py          # events -> sim/run/tools/wake.log, socket sim/run/tools/cdc.sock
    python3 software/cdc.py status                  # any firmware command
    python3 software/micscope.py --capture-cmd "python3 sim/twin/sim_arecord.py"   # live scope at :8778
--speed 0 runs as fast as possible (offline scoring); a CSV of truth vs estimate lands in run-dir/doa_log.csv.
"""
import argparse
import csv
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sim.acoustics.audio_world import AudioWorld, BLOCK          # noqa: E402
from sim.acoustics.doa import SR                                 # noqa: E402
from sim.twin.xvf3800 import VirtualXVF3800                       # noqa: E402
from sim.twin.xiao import VirtualXiao                             # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("--scenario", default=os.path.join(os.path.dirname(__file__), "scenarios", "default.json"))
    ap.add_argument("--pose", choices=["hat", "spider"], help="override scenario array_pose")
    ap.add_argument("--xmos", choices=["i2s", "usb"], help="override scenario xmos_firmware")
    ap.add_argument("--dynamic", action="store_true", help="step MuJoCo physics (head can move)")
    ap.add_argument("--speed", type=float, default=1.0, help="1.0 = real time, 0 = as fast as possible")
    ap.add_argument("--duration", type=float, default=0.0, help="stop after S simulated seconds (0 = run until Ctrl-C)")
    ap.add_argument("--run-dir", default=os.path.join(os.path.dirname(__file__), "run"))
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()

    with open(a.scenario) as f:
        sc = json.load(f)
    pose = a.pose or sc.get("array_pose", "hat")
    fw = a.xmos or sc.get("xmos_firmware", "i2s")
    dynamic = a.dynamic or sc.get("dynamic", False)
    run_dir = os.path.abspath(a.run_dir)
    os.makedirs(os.path.join(run_dir, "tools"), exist_ok=True)

    world = AudioWorld(array_pose=pose, dynamic=dynamic, source_specs=sc.get("sources", []),
                       noise_dbfs=sc.get("mic_noise_dbfs", -75.0))
    xmos = VirtualXVF3800(firmware=fw, world=world, vad_dbfs=sc.get("vad_dbfs", -45.0))
    xiao = VirtualXiao(xmos, run_dir, log=(lambda s: None) if a.quiet else print)
    moves = sorted(sc.get("moves", []), key=lambda m: m["t"])

    print("scenario %s | array %s | xmos firmware %s | dynamic %s" % (os.path.basename(a.scenario), pose, fw, dynamic))
    print("duck faces world %s; sources:" % world.facing().round(2).tolist())
    for s in world.sources:
        tr = world.truth(s)
        print("  %-10s pos %s -> az %.1f el %.1f range %.2f m" % (s.name, list(s.pos), tr["az"], tr["el"], tr["range"]))
    print("CDC port: %s\naudio sock: %s\n" % (xiao.port_link, xiao.audio_sock_path))

    csvf = open(os.path.join(run_dir, "doa_log.csv"), "w", newline="")
    cw = csv.writer(csvf)
    cw.writerow(["t", "truth_az", "truth_speech", "est_az", "est_valid", "xmos_speech", "xiao_vad_active", "wakes"])
    t_wall0 = time.perf_counter()
    next_print = 0.0
    try:
        while True:
            for m in list(moves):
                if world.t >= m["t"]:
                    world.set_source_pos(m["source"], m["pos"]); moves.remove(m)
                    if not a.quiet: print("t=%.1f move %s -> %s" % (world.t, m["source"], m["pos"]))
            block, truth = world.step_block()
            L, R = xmos.process_block(block)
            xiao.on_i2s_block(L, R)
            first = next(iter(truth["sources"].values())) if truth["sources"] else {"az": float("nan")}
            cw.writerow(["%.2f" % truth["t"], "%.1f" % first["az"], int(truth["speech"]), "%.1f" % xmos.doa_deg,
                         int(xmos.doa_valid), int(xmos.speech), int(xiao.vad_active), xiao.vad_wakes])
            if not a.quiet and world.t >= next_print:
                next_print += 1.0
                print("t=%5.1fs truth az %6.1f speech %d | xmos doa %6.1f valid %d speech %d | xiao vad_active %d wakes %d i2s %s" % (
                    world.t, first["az"], truth["speech"], xmos.doa_deg, xmos.doa_valid, xmos.speech,
                    xiao.vad_active, xiao.vad_wakes, "on" if xiao.i2s_running else "OFF"))
            if a.duration and world.t >= a.duration:
                break
            if a.speed > 0:
                target = t_wall0 + world.t / a.speed
                dt = target - time.perf_counter()
                if dt > 0:
                    time.sleep(dt)
    except KeyboardInterrupt:
        pass
    finally:
        csvf.close()
        xiao.alive = False
    print("done: %.1f s simulated, log %s" % (world.t, os.path.join(run_dir, "doa_log.csv")))


if __name__ == "__main__":
    main()
