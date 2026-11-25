#!/usr/bin/env python3
"""Place the hardened top macros with a dataflow-oriented floorplan.

LibreLane runs GeneratePDN before global placement, so every macro in the
MACROS configuration must have a fixed location.  This script reads the macro
LEF dimensions and places them without touching standard cells:

  - the ACTMEM on the left, feeding the feature loader;
  - the feature loader beside it, with its input side facing the ACTMEM;
  - the 32 tall scaler groups below, in an 8 x 4 grid, so their top-to-bottom
    dataflow stays vertical.

The die is square and large enough for the fixed macro grid.  Standard-cell
glue is placed later by OpenROAD.
"""

from __future__ import annotations

import argparse
import math
import re
from pathlib import Path

SIZE_RE = re.compile(r"^\s*SIZE\s+([0-9.]+)\s+BY\s+([0-9.]+)\s*;", re.MULTILINE)

SCALER_COLUMNS = 8
SCALER_ROWS = 4
SCALER_COUNT = SCALER_COLUMNS * SCALER_ROWS


def lef_size(path: Path) -> tuple[float, float]:
    match = SIZE_RE.search(path.read_text())
    if not match:
        raise SystemExit(f"no SIZE found in {path}")
    return float(match.group(1)), float(match.group(2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--macro-root", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--margin", type=float, default=100.0)
    parser.add_argument("--gap", type=float, default=50.0)
    args = parser.parse_args()

    root = args.macro_root
    group_w, group_h = lef_size(root / "output_scaler_group/lef/output_scaler_group.lef")
    feature_w, feature_h = lef_size(root / "feature_loader/lef/feature_loader.lef")
    ram_w, ram_h = lef_size(root / "ram_2w2r/lef/ram_2w2r.lef")

    instances: list[tuple[str, str, float, float]] = [
        ("ram_2w2r", "u_top.u_activation_buffer", ram_w, ram_h),
        ("feature_loader", "u_top.u_feature_loader", feature_w, feature_h),
    ]
    for index in range(SCALER_COUNT):
        instances.append(
            (
                "output_scaler_group",
                f"u_top.u_output_scaler_set.g_group[{index}].u_output_scaler_group",
                group_w,
                group_h,
            )
        )

    positions: dict[str, tuple[float, float]] = {}

    # Left-to-right top band: ACTMEM -> feature loader.
    ram_x = args.margin
    ram_y = args.margin
    feature_x = ram_x + ram_w + args.gap
    feature_y = args.margin
    positions["u_top.u_activation_buffer"] = (ram_x, ram_y)
    positions["u_top.u_feature_loader"] = (feature_x, feature_y)

    # The scaler grid sits below the top band.  Eight columns by four rows
    # keeps the 32 tall macros close to square and leaves vertical channels
    # between columns for the top-to-bottom dataflow.
    grid_x = args.margin
    grid_y = args.margin + max(ram_h, feature_h) + 2 * args.gap
    for index in range(SCALER_COUNT):
        column = index % SCALER_COLUMNS
        row = index // SCALER_COLUMNS
        x = grid_x + column * (group_w + args.gap)
        y = grid_y + row * (group_h + args.gap)
        positions[
            f"u_top.u_output_scaler_set.g_group[{index}].u_output_scaler_group"
        ] = (x, y)

    max_x = max(positions[name][0] + w for _, name, w, _ in instances)
    max_y = max(positions[name][1] + h for _, name, _, h in instances)
    side = math.ceil(
        max(max_x + args.margin, max_y + args.margin, 1000.0) / 10.0
    ) * 10.0

    total_area = sum(w * h for _, _, w, h in instances)
    print(f"# packed macro area: {total_area / 1e6:.2f} mm^2")
    print(f"# die side: {side:.0f} um, macro-only util: {total_area / (side * side):.3f}")

    for macro in ("ram_2w2r", "feature_loader", "output_scaler_group"):
        print(f"{macro}:")
        for candidate, name, _, _ in instances:
            if candidate != macro:
                continue
            px, py = positions[name]
            print(f"  {name}:")
            print(f"    location: [{px:.2f}, {py:.2f}]")
            print("    orientation: N")

    if args.config is not None:
        import yaml

        config = yaml.safe_load(args.config.read_text())
        for macro in ("ram_2w2r", "feature_loader", "output_scaler_group"):
            config["MACROS"][macro]["instances"] = {}
            for candidate, name, _, _ in instances:
                if candidate != macro:
                    continue
                px, py = positions[name]
                config["MACROS"][macro]["instances"][name] = {
                    "location": [round(px, 2), round(py, 2)],
                    "orientation": "N",
                }
        config["FP_SIZING"] = "absolute"
        config["DIE_AREA"] = [0, 0, side, side]
        config["PL_TARGET_DENSITY_PCT"] = 65
        args.config.write_text(yaml.safe_dump(config, sort_keys=False))
        print(f"# wrote {args.config}")


if __name__ == "__main__":
    main()
