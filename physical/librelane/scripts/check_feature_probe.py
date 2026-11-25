"""Check the feature loader's pin escape and global congestion."""

import argparse
from decimal import Decimal
from pathlib import Path
import re

OUTPUT_COUNT = 288 * 9
MIN_PITCH_UM = Decimal("0.84")
MAX_METAL3_USAGE = Decimal("65")


def check_pins(design_def):
    units = re.search(r"(?m)^UNITS DISTANCE MICRONS\s+(\d+)\s*;", design_def)
    die = re.search(r"(?m)^DIEAREA\s+\(.*?\)\s*\(\s*(-?\d+)", design_def)
    pin_section = re.search(r"(?ms)^PINS\s+\d+\s*;(.*?)^END PINS\s*$", design_def)
    if units is None or int(units[1]) == 0 or die is None or pin_section is None:
        raise ValueError("Missing or invalid DEF units, die area, or pin section")
    dbu = int(units[1])
    east = int(die[1])
    pins = {}
    for entry in pin_section[1].split(";"):
        pin = re.match(r"\s*-\s+data_o\[(\d+)\]\s", entry.replace("\\", ""))
        if pin is None:
            continue
        index = int(pin[1])
        layer = re.search(
            r"\+ LAYER Metal3\s+\(\s*-?\d+\s+-?\d+\s*\)\s*\(\s*(-?\d+)", entry
        )
        placed = re.search(r"\+ (?:PLACED|FIXED)\s+\(\s*(-?\d+)\s+(-?\d+)\s*\)\s+N\b", entry)
        if layer is None or placed is None or int(placed[1]) + int(layer[1]) < east:
            raise ValueError(f"data_o[{index}] does not reach the Metal3 east edge")
        if index in pins:
            raise ValueError(f"Duplicate data_o[{index}] in DEF")
        pins[index] = int(placed[2])
    if pins.keys() != set(range(OUTPUT_COUNT)):
        raise ValueError(f"Expected data_o[0:{OUTPUT_COUNT - 1}], found {len(pins)} output pins")

    ys = sorted(pins.values())
    pitch = Decimal(min(b - a for a, b in zip(ys, ys[1:]))) / dbu
    print(f"{len(pins)} east-edge Metal3 output pins, minimum pitch {pitch} µm")
    if pitch < MIN_PITCH_UM:
        raise ValueError(f"Minimum pin pitch must be at least {MIN_PITCH_UM} µm")


def check_grt(log):
    report = log.rsplit("Final congestion report:", 1)
    if len(report) == 1:
        raise ValueError("Missing final global routing congestion report")
    rows = {
        name: (Decimal(usage), int(overflow))
        for name, usage, overflow in re.findall(
            r"^\s*(Metal3|Total)\s+\d+\s+\d+\s+([\d.]+)%"
            r"[^\S\n]+\d+\s*/\s*\d+\s*/\s*(\d+)\s*$",
            report[1],
            re.MULTILINE,
        )
    }
    if rows.keys() != {"Metal3", "Total"}:
        raise ValueError("Missing Metal3 or Total row in final global routing report")
    usage = rows["Metal3"][0]
    overflow = rows["Total"][1]
    print(f"Metal3 usage {usage}%, total overflow {overflow}")
    if usage > MAX_METAL3_USAGE or overflow:
        raise ValueError(f"Global routing requires Metal3 usage ≤ {MAX_METAL3_USAGE}% and zero overflow")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("pins", "grt"))
    parser.add_argument("file", type=Path)
    args = parser.parse_args()
    check = check_pins if args.stage == "pins" else check_grt
    try:
        check(args.file.read_text())
    except (OSError, ValueError) as error:
        parser.exit(1, f"{args.file}: {error}\n")


if __name__ == "__main__":
    main()
