# Results

Result data and Synopsys report parsing.

## Tracked result data

`tests/results/` contains CSV result data from the 2025 thesis work (thesis data
— not gitignored). `results/` holds generated artifacts (gitignored).

## parse_reports.py

`results/parse_reports.py` parses text-format Synopsys Design Compiler /
PrimeTime reports and produces dataframes and figures summarising area, power,
and timing (pie charts, bar plots, etc.).

Usage:

```
python parse_reports.py <report_file> [report_type]
```

Examples:

```
python parse_reports.py synth/reports/power_qr_acc_top.txt power
python parse_reports.py synth/reports/area_qr_acc_top.txt area
python parse_reports.py synth/reports/power_qr_acc_top.txt auto
```

`report_type` options:

| Option | Meaning |
|--------|---------|
| `power` | Parse as a power report |
| `area`  | Parse as an area report |
| `auto`  | Auto-detect report type (default) |

Requires: pandas, seaborn, matplotlib (see `env.yml`).
