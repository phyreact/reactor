#!/usr/bin/env python3
"""Download the pinned official XMOS image; never flash or overwrite files."""
import argparse
import hashlib
from pathlib import Path
import urllib.request

COMMIT = "f3908280ef4ab59048ace970eaf12ead7e640b2e"
URL = (
    "https://raw.githubusercontent.com/respeaker/reSpeaker_XVF3800_USB_4MIC_ARRAY/"
    + COMMIT
    + "/xmos_firmwares/i2s/application_xvf3800_i2s_slave_v1.0.8_16k.bin"
)
SHA256 = "9dc3308a4db8570603bcc88103d2f0de0291cc92a384d2b25de6eef6f2d99eb8"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    with urllib.request.urlopen(URL, timeout=60) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() != SHA256:
        raise ValueError("Downloaded firmware SHA-256 does not match")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("xb") as stream:
        stream.write(data)
    print("Verified XMOS I2S slave 1.0.8 / 16 kHz firmware.")


if __name__ == "__main__":
    main()
