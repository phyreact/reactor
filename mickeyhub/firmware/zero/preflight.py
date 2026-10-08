#!/usr/bin/env python3
"""Read-only checks on the target ZERO; prints actual UART/PWM/I2C device names."""
import json
from pathlib import Path
import struct
import sys

DT = Path("/sys/firmware/devicetree/base")


def words(path):
    data = path.read_bytes()
    if len(data) % 4:
        raise ValueError(str(path))
    return list(struct.unpack(">" + "I" * (len(data) // 4), data))


def strings(path):
    return path.read_bytes().rstrip(b"\0").decode().split("\0")


def main():
    errors = []
    if not DT.exists() or "radxa,zero-3w" not in strings(DT / "compatible"):
        raise RuntimeError("This check requires the actual Radxa ZERO 3W")
    phandles = {}
    for p in DT.rglob("phandle"):
        phandles[words(p)[0]] = p.parent
    symbols = DT / "__symbols__"
    report = {}
    for name, expected in {
            "uart9": {(4, 22, 4), (4, 21, 4)},
            "uart5": {(3, 19, 4), (3, 18, 4)},
            "i2c4": {(4, 10, 1), (4, 11, 1)},
            "pwm14": {(3, 20, 1)}}.items():
        try:
            node = DT / strings(symbols / name)[0].lstrip("/")
            if strings(node / "status") != ["okay"]:
                raise ValueError("device is not enabled")
            pins = set()
            for handle in words(node / "pinctrl-0"):
                values = words(phandles[handle] / "rockchip,pins")
                if len(values) % 4:
                    raise ValueError("invalid pinctrl data")
                pins |= {tuple(values[i:i + 3]) for i in range(0, len(values), 4)}
            if pins != expected:
                raise ValueError(f"pinmux is {sorted(pins)}, expected {sorted(expected)}")
            report[name] = {"node": str(node), "pins": sorted(pins), "devices": []}
            kind = "tty" if name.startswith("uart") else ("i2c-adapter" if name.startswith("i2c") else "pwm")
            for device in (Path("/sys/class") / kind).glob("*"):
                for of_node in (device / "device/of_node", device / "of_node"):
                    if of_node.exists() and of_node.resolve() == node.resolve():
                        report[name]["devices"].append(str(device))
                        break
            if not report[name]["devices"]:
                errors.append(f"{name}: DT enabled but no corresponding Linux device")
        except (OSError, KeyError, ValueError) as exc:
            errors.append(f"{name}: {exc}")
    try:
        node = DT / "i2c-box-hat"
        if strings(node / "compatible") != ["i2c-gpio"]:
            raise ValueError("HAT bus is not i2c-gpio")
        gpio1 = DT / strings(symbols / "gpio1")[0].lstrip("/")
        for prop, pin in (("sda-gpios", 0), ("scl-gpios", 1)):
            values = words(node / prop)
            if len(values) != 3 or phandles[values[0]] != gpio1 or values[1:] != [pin, 6]:
                raise ValueError(f"{prop}: wrong bank/pin/open-drain flags")
        buses = []
        for device in Path("/sys/class/i2c-adapter").glob("i2c-*"):
            for of_node in (device / "of_node", device / "device/of_node"):
                if of_node.exists() and of_node.resolve() == node.resolve():
                    buses.append(str(device))
                    break
        if not buses:
            raise ValueError("No GPIO I2C adapter; check CONFIG_I2C_GPIO/I2C_CHARDEV")
        report["hat_i2c"] = {"devices": buses}
    except (OSError, KeyError, ValueError) as exc:
        errors.append(f"hat_i2c: {exc}")
    report["errors"] = errors
    report["scope"] = "DT and device enumeration only; pin ownership, voltages and waveforms need hardware checks"
    print(json.dumps(report, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, RuntimeError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
