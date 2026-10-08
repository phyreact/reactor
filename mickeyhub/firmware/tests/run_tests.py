#!/usr/bin/env python3
import os
from pathlib import Path
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix="box-r21r-tests-") as directory:
    executable = Path(directory) / "test_power"
    library = Path(directory) / "protocol.dylib"
    subprocess.run(["clang", "-std=c11", "-Wall", "-Wextra", "-Werror",
                    "-fsanitize=address,undefined", "-g",
                    "common/protocol.c", "common/power.c", "tests/test_power.c",
                    "-o", str(executable)], cwd=root, check=True)
    subprocess.run([str(executable)], check=True)
    tof_test = Path(directory) / "test_tof_platform"
    subprocess.run(["clang", "-std=c11", "-Wall", "-Wextra", "-Werror",
                    "-fsanitize=address,undefined", "-g",
                    "zero/tof/linux_platform.c", "tests/test_tof_platform.c",
                    "-o", str(tof_test)], cwd=root, check=True)
    subprocess.run([str(tof_test)], check=True)
    subprocess.run(["clang", "-shared", "-fPIC", "-Wall", "-Wextra", "-Werror",
                    "common/protocol.c", "-o", str(library)], cwd=root, check=True)
    subprocess.run([sys.executable, "tests/test_zero.py"], cwd=root, check=True,
                   env={**os.environ, "BOX_PROTOCOL_LIBRARY": str(library)})
    subprocess.run([sys.executable, "tests/test_peripherals.py"], cwd=root, check=True)
