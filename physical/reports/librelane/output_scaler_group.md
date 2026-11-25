# output_scaler_group hardening report

Status: views generated, routing DRC clean, **signoff incomplete**.

## Configuration

| Item | Value |
|---|---|
| Source | `physical/librelane/src/output_scaler_group.sv` (8 lanes) |
| Target clock | 25 MHz (40 ns), 5% jitter, 20% I/O delay |
| Flow | LibreLane 3.0.3, `ihp-sg13g2`, `sg13g2_stdcell` |
| Run | `runs/output_scaler_group` |

## Area

| Item | Value |
|---|---:|
| Die area | 1,733,930 um² |
| Core area | 1,674,800 um² |
| Standard cells | 146,784 |
| Standard-cell area | 1,192,930 um² |
| Core utilization | 71.2% |
| LEF size | 1307.460 x 1326.180 um (= 1,733,927.3 um²) |
| Buffers | 72,565 |
| Inverters | 6,631 |
| Combinational cells | 65,191 |

The synthesised netlist had about 80k cells; placement repair and resizing
raised the final count to 146,784.

## Timing (post-PnR, `55-openroad-stapostpnr`)

| Corner | Setup WNS (ns) | Setup TNS (ns) | Setup violations | Hold WNS (ns) |
|---|---:|---:|---:|---:|
| `nom_fast_1p32V_m40C` | 12.2058 | 0.0000 | 0 | 14.3757 |
| `nom_typ_1p20V_25C` | 6.9169 | 0.0000 | 0 | 14.5634 |
| `nom_slow_1p08V_125C` | **-2.3120** | **-35.2960** | **40** | 14.8933 |

Hold is clean at every corner. Setup is clean at fast and typical, but the slow
corner misses 25 MHz by 2.31 ns on 40 paths. There are also 5 max-fanout
violations. The macro is therefore **not 25 MHz signoff clean**. It can be used
in a slower top-level flow, but a 25 MHz signoff requires re-hardening at a
longer period or a timing ECO.

## Physical verification

| Check | Result |
|---|---|
| Detailed routing DRC | 0 errors after 5 iterations |
| Antenna | clean; 49 antenna diodes inserted |
| Disconnected pins | 2 (0 critical) |
| Magic DRC (`64-magic-drc`) | 0 errors |
| KLayout XOR (`62/63`) | 0 differences |
| KLayout DRC (`65-klayout-drc`) | **not completed**; stopped after 5 h with no progress |

Magic DRC and XOR are clean. KLayout DRC is the only missing physical signoff
step. It must be run to completion on the staged GDS before this macro is called
DRC clean.

## Staged views

The flow was stopped at KLayout DRC, so the views were copied manually:

| View | Source step |
|---|---|
| GDS | `58-klayout-streamout/output_scaler_group.gds` |
| LEF | `60-magic-writelef/output_scaler_group.lef` |
| Netlist | `06-yosys-synthesis/output_scaler_group.nl.v` |
| Liberty (3 corners) | `55-openroad-stapostpnr/<corner>/output_scaler_group__<corner>.lib` |

Destination: `physical/build/librelane/macros/output_scaler_group/`.

## Open items

1. Run KLayout DRC to completion, or decide that Magic DRC + XOR is sufficient
   for the macro-level signoff.
2. Re-harden at a longer period (50 ns or 100 ns) if 25 MHz macro signoff is
   required. At 100 ns the slow-corner path has about 57.7 ns of margin.
3. Resolve the 5 max-fanout violations if the macro is re-hardened.
