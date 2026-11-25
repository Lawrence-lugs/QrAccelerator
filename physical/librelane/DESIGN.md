# Hierarchical LibreLane physical flow

Date: 2026-11-21
Repo: `QrAccelerator-physical`, branch `feat/yosys-synthesis`
Status: in progress; `feature_loader` hardening is running, the remaining macros and top are pending

## Intent

Build a reproducible LibreLane flow for the digital part of `qr_acc_top`,
hierarchically: harden the large blocks into macros, then assemble a digital-only
top around them. The top is intended to sit inside a larger SoC, so there is no
pad ring. The logic blocks use a lower-layer-only PDN; the memory and top use the
full PDN so the macro power pins are connected.

The full top is ~80k generic cells (~109k after mapping). The earlier flat IHP
mapping hit the 16 GB Docker limit in `techmap`, so the hierarchy is not optional.

## Decisions from the user

| Topic | Decision |
|---|---|
| Top scope | Digital-only top; analog buses are not top pins |
| Analog handling | Tie `from_analog` to zero, leave `to_analog` open; synthesis trims analog-side logic |
| Macros | `output_scaler_group` (8 lanes each, 32 macros), `feature_loader`, and the physical ACTMEM |
| `seq_acc` | Not hardened; it stays in top glue and instantiates the RTL `shift_add_tree` |
| ACTMEM depth | 256 KiB |
| Memory path | Keep `MODEL_MEM`; substitute a physical `ram_2w2r` under `physical/` |
| RTL edits | None; physical overrides only |
| Clock | 50 MHz failed. The scaler macro was hardened at 25 MHz (40 ns), but its slow corner missed by 2.31 ns. `feature_loader` is hardened at 10 MHz (100 ns) because its 25 MHz route hit a detailed-route violation plateau. The top uses 10 MHz, 5% jitter = 5.0 ns |
| I/O budget | 20% of period (20 ns at 10 MHz; 8 ns for the 25 MHz scaler macro) |
| Analog/reset | False paths |
| Default driver | `sg13g2_buf_1` for data; `sg13g2_buf_16` for clock |
| Floorplan | `feature_loader`: wide (`height/width = 0.7`) at 40% util, data in on the left and data out on the right. The 1.4:1 shape leaves enough east-edge tracks for 2,592 outputs. Scaler groups: 2:1 tall (`height/width = 2.0`) at 65%, data top to bottom. Top: square at 65% target density. Macros are on a deterministic grid because PDN runs before global placement |
| Pin placement | `IO_PIN_ORDER_CFG` for the feature loader and scaler groups; automatic for the memory |
| PDN | `PDN_MULTILAYER: false` for logic blocks; `true` for the memory and top with `PDN_MACRO_CONNECTIONS` |
| Path groups | Report OpenSTA `in2reg` / `reg2out` / `reg2reg` / `feedthrough` with WNS/TNS |

## ACTMEM: why the physical `ram_2w2r`, not `activation_buffer`

`MODEL_MEM` is the intended switch:

- defined → `qr_acc_top` instantiates the behavioural `ram_2w2r`
- undefined → it instantiates `activation_buffer` + `sram_32bank_8b`

However, `activation_buffer.sv` was added in `a7c2b35` (2025-03-03) and
`sram_32bank_8b.sv` in `7b8d08e` (2025-06-30), both long before this branch, and
neither changed between `54f0a0c` and HEAD. Per the user's rule, those files are
not ours to edit. `sram_32bank_8b.sv` is also only a comment, and the existing
`activation_buffer` semantics are not `ram_2w2r`-equivalent (read-prioritised,
first four banks only, byte addresses passed straight through).

Therefore the physical flow keeps `MODEL_MEM` defined and substitutes a new
**physical `ram_2w2r`** implementation under `physical/actmem/`. The behavioural
`rtl/memory/ram_2w2r.sv` remains untouched for the RTL designer and for
simulation. The physical file list excludes the behavioural file and includes
the physical one; both have the same port list.

The physical memory:

- 256 KiB = 262,144 bytes
- 8 banks × 32 bits = 256-bit rows
- 8,192 rows of 32 bytes
- `RM_IHPSG13_2P_1024x32_c2_bm_bist` (1024×32, 2-port, 264,167.28 µm²)
- 8 row banks × 8 column banks = **64 SRAM macros**
- 64 × 264,167.28 = **16,906,705.92 µm²** of macro area
- same word rotation and byte order as the behavioural model, including the
  internal-port read reversal; the existing `actmem_2w2r_ihp` simulation is the
  starting point and will be extended from 256×32 to 1024×32 macros.

The top wrapper sets `globalBufferDepth = 262144`. No RTL files change.

## Digital-only top

New file `physical/librelane/src/qr_acc_top_phys.sv`:

- instantiates `qr_acc_top #(.globalBufferDepth(262144))`
- flat ports: `clk`, `nrst`, `bus_req_data[31:0]`, `bus_req_addr[31:0]`,
  `bus_req_wen`, `bus_req_valid`, `bus_resp_ready`,
  `bus_resp_data[31:0]`, `bus_resp_rd_valid`, `bank_select[7:0]`
- ties `from_analog` to zero and leaves `to_analog` open
- packs/unpacks `bus_req_t` / `bus_resp_t` internally

This removes the ~91k analog pins while keeping the digital control, memory,
compute and bus logic. The analog-side logic that only feeds `to_analog` will be
trimmed; that is the agreed trade-off for the first flow.

## Ties and later analog integration

The digital-only wrapper drives `from_analog` to zero and leaves `to_analog`
unconnected. This is not the final analog interface; it is a deliberate first-flow
partition. The later SoC integration must restore the full interface.

### `from_analog` — tied to zero

`from_analog_t` is 7,968 bits per plane (63,744 bits for 8 planes):

| Field | Width | Tie |
|---|---:|---|
| `SA_OUT` | 32 | 0 |
| `ADC_OUT` | 3,840 (`compCount=15` × 256) | 0 |
| `ADC_CODE` | 4,096 (256 × 16) | 0 |

Tying the ADC/SA outputs low means the digital accumulator sees zero-valued
analog results. The flow is for physical feasibility; it does not verify analog
function.

### `to_analog` — left open

`to_analog_t` is 3,402 bits per plane (27,216 bits for 8 planes):

| Field | Width |
|---|---:|
| 12 switch-matrix arrays (`PSM_*`, `NSM_*`) | 3,072 (12 × 256) |
| `WL` | 256 |
| `PCH` | 1 |
| `WR_DATA` | 32 |
| `WRITE` | 1 |
| `CSEL` | 32 |
| `SAEN` | 1 |
| `NF`, `NFB`, `M2A`, `M2AB`, `R2A`, `R2AB` | 6 |
| `CLK` | 1 |

Leaving these open lets synthesis trim the analog switch/SRAM/ADC control
logic. In particular there is no top-level analog clock pin; `to_analog.CLK` is
inside this bus.

### What remains a pin

`bank_select[7:0]` stays a digital output pin. It is a bank select for the
analog/SRAM side, not part of the trimmed analog bus, and is constrained as a
false path in the first flow.

### Later analog datapath integration

When the analog macros are added:

- use the full `qr_acc_top` (or a wrapper that restores both analog buses);
- do not tie `from_analog` or leave `to_analog` open;
- budget for the ~91k-pin boundary, or partition the analog interface into
  smaller macros;
- re-run the top with the full analog timing constraints, not the false paths
  used here;
- keep the digital-only wrapper as a flow-debug vehicle, not as the final SoC
  block.

The exact wrapper code and tie assignments are in
`physical/librelane/src/qr_acc_top_phys.sv`; the flow README repeats the
integration notes.

## Hierarchy and macro views

| Macro | Size | Source |
|---|---:|---|
| `output_scaler_group` | 8 lanes, ~80k mapped gates | `physical/librelane/src/output_scaler_group.sv` |
| `feature_loader` | 19,899 generic cells | `rtl/feature_loader/feature_loader.sv` |
| `ram_2w2r` | 64 SRAM macros + wrapper | `physical/actmem/ram_2w2r_ihp.sv` |

`shift_add_tree` is **not** a macro in the final top. It is only 6,464 generic
cells, but in the top configuration it has `numOutputs = 256`, which is about
11,000 pins (8 planes x 256 x 4-bit `partial_i`, plus 256 x 11-bit `sum_o`).
That pin count is not realisable around a small hard macro, so the tree stays in
top glue. The top is still about 37k standard cells after the three macros, well
below the flat 80k-cell top that exhausted the 16 GB VM. `harden-tree` remains
in the Makefile only as an optional experiment; the top flow does not use it.

The whole 256-lane `output_scaler_set` was attempted as one macro first: Yosys
expanded it to ~2.57M cells and ABC failed with status 9. The group split is the
response. The physical `output_scaler_set` stays in top glue (~3k cells) and
keeps the 256-entry weight memory; it instantiates 32 `output_scaler_group`
macros. No RTL file changes.

The remaining top glue is ~37k generic cells plus the macro instances. It
includes the physical `output_scaler_set`, `seq_acc` (which instantiates the RTL
`shift_add_tree`), `padder`, `mm_output_aligner`, `piso_write_queue`,
`wsacc_pe_cluster`, `qracc_csr`, `qracc_controller`, `qr_acc_wrapper`,
`wr_controller`, `twos_to_bipolar`, and `bipolar_bias_sub`.

Each hardened macro produces LEF, GDS, LIB and a Verilog netlist. The top flow
uses macro blackboxes and `MACROS` config entries. LibreLane's `GeneratePDN`
runs before global placement and rejects unplaced macros, so the macros are not
free-floating: each one has a deterministic `instances` location. For the
memory, the 64 SRAM blocks are placed on an 8x8 grid, rotated 90 degrees, inside
the 5800 x 4200 um die. The top macro grid is generated from the hardened LEF
sizes by `scripts/pack_top_macros.py`. It follows the datapath: ACTMEM and the
wide feature loader form the left-to-right top band, and the 32 tall scaler
groups sit below in an 8 x 4 grid with vertical top-to-bottom flow. The die is
square and sized for the fixed macro grid.

## Flow and Makefile

New directory `physical/librelane/` with a Makefile:

```text
make preprocess        # sv2v each block/top into build/librelane/preprocessed
make harden-feature    # feature_loader
make harden-scaler-group  # 8-lane output_scaler_group, 32 macros
make harden-ram        # physical ram_2w2r (64 SRAM macros)
make harden-tree       # optional: not used by the top (11k-pin macro)
make top               # digital-only top with the three macros
make clean
```

Every harden target runs LibreLane with `env -u PYTHONPATH` (the image's
miniforge 3.13 `PYTHONPATH` breaks LibreLane 3.0.3 under system Python 3.12),
using the direct `/usr/local/bin/librelane` entry point so it sees the image's
OpenROAD 2.7 rather than the obsolete 2.6 wrapper toolchain. Arguments:
`--manual-pdk --pdk ihp-sg13g2 --pdk-root /foss/pdks --scl sg13g2_stdcell`, and
`--save-views-to physical/build/librelane/macros/<name>`.

The top target depends on the three macro view sets. Its file list contains the
top wrapper, the glue RTL, and blackbox stubs for the three macros. The
behavioural `ram_2w2r` and the hardened blocks' RTL are excluded from top
synthesis.

The top runs at 10 MHz (100 ns). If it misses timing, the period is changed in
`configs/qr_acc_top_phys.yaml` and `sdc/qr_acc_top_phys.sdc`, then the flow is
rerun; there is no automatic frequency loop in the Makefile.

## Constraints

| Item | Value |
|---|---|
| PDK / SCL | `ihp-sg13g2` / `sg13g2_stdcell` |
| Clock | `clk`, 100 ns (10 MHz) for `feature_loader` and the top; 40 ns (25 MHz) for the scaler macro |
| Jitter | 5% of period: 5.0 ns at 10 MHz, 2.0 ns at 25 MHz |
| I/O delay | 20% of period |
| Input driver | `sg13g2_buf_1/A` |
| Clock driver | `sg13g2_buf_16/A` |
| Insertion buffer | `sg13g2_buf_1/A/X` |
| Floorplan | Logic blocks: relative, 40% wide for the feature loader, 65% tall for the scaler groups. Memory: absolute 5800 x 4200 um. Top: absolute square from `pack_top_macros.py` |
| Macro placement | Fixed `instances` locations: 8x8 SRAM grid, and a packed top grid from LEF sizes |
| PDN | top uses `PDN_MULTILAYER: true` and macro connections |
| Pins | automatic |
| False paths | `nrst`, `bank_select` |
| Path groups | built-in `in2reg` / `reg2out` / `reg2reg` / `feedthrough` |

The top SDC flattens the bus: `bus_req_*` are inputs with 8 ns input delay,
`bus_resp_*` are outputs with 8 ns output delay, and `bank_select`/`nrst` are
false paths. Block SDCs use the same clock/jitter/driver settings and a 20% I/O
budget at their own boundaries. `shift_add_tree` has no clock; its block SDC uses
a virtual clock and feedthrough input/output delays.

## Risks and fallbacks

1. **256 KiB memory floorplan.** The 8×8 SRAM array is about 5.8 mm ×
   4.2 mm including the wrapper. The memory macro's own 70% square core would
   be too narrow for that array, so the memory macro uses an absolute
   rectangular die. At the top, the 32 scaler groups (~1.73M µm² each), feature
   loader (~5.4M µm²) and memory (~17.6M µm²) are about 78M µm²; a 65% square
   top is about 11 mm on a side, which can hold the 5.8 mm wide memory macro.
   Start with the square target; if placement fails, use a rectangular 65%
   fallback.
2. **`shift_add_tree` is purely combinational and pin-heavy.** In the top it has
   `numOutputs = 256` and about 11,000 pins. That is not a usable hard macro, so
   it stays in top glue. If the resulting top still exceeds the 16 GB VM, the
   fallback is a digital-only `seq_acc` wrapper (analog buses tied/trimmed)
   hardened as one macro; that keeps the tree inside the macro and removes the
   wide tree boundary.
3. **16 GB Docker limit.** The top glue is ~43.5k cells and should fit once the
   wide blocks are macros. If it does not, the next hierarchy step is a
   digital-only `seq_acc` macro or `wsacc_pe_cluster`.

   The `feature_loader` block also exposed a placement limit: at 70% core
   utilization its 25 MHz run failed the post-CTS resizer with `[DPL-0036]`
   after LibreLane's default 50% buffer-insertion budget. With the budget
   reduced to 5%, the same run then hit `[RSZ-0060]` after inserting 17,368
   hold buffers. The 2 ns jitter was being applied to hold as well as setup.
   The SDC files now set `set_clock_uncertainty -hold 0.1`. The feature config
   uses a wide 40% core (`height/width = 0.7`) and 5% setup/hold buffer caps.
   Its first 65% run completed placement and CTS but failed global routing with
   Metal3 at 103% and 161,782 overflow, so the core was opened to 50%. At 50%
   the 25 MHz route passed global routing with a 15% derate, but detailed
   routing ended its first iteration with 1,002,224 violations, mostly
   Metal2/Metal3 shorts, and repeated the same count at iteration 1. The macro
   is therefore re-hardened at the 10 MHz top frequency and opened to 40%. The
   15% derate still left 6,015 overflowed tiles, mostly Metal3 and Metal5; the
   current retry uses `GRT_ADJUSTMENT: 0.05`. Detailed routing did converge to
   zero DRC after 14 iterations, but the first post-route slow corner without
   post-GPL repair had -43.9 ns setup WNS on an `addr_i` -> flop path with
   fanout 109/169. Post-GPL design repair is therefore enabled, but output-port
   buffering is disabled: buffering all 2,592 `data_o` pins made detailed
   routing much worse. Global antenna repair is
   still disabled for now: the east-edge nets produced 1,271 violations, and
   `repair_antennas` inserted 214,977 diodes before a heap-underflow error.
   Antenna fixing is deferred to top integration. `DRT_THREADS: 16` is used,
   and only one PnR flow may run at a time. The other blocks keep 65% and the
   same hold and buffer settings.

   The repaired netlist does not converge: detailed routing starts at 486,257
   violations and plateaus near 167,000 with ~94,000 Metal2 shorts. The cause
   appears related to pin geometry. All 2,592 `data_o` pins sit on Metal3 on the east edge, on a
   0.42 um pitch, in a contiguous 1088 um band: `tracks_per_pin` is 1, so no
   free Metal3 track exists between any two adjacent pins and the outer 42% of
   the edge is unused. A die height of at least 2177 um gives one free track
   per pin, and 3266 um gives two. Global routing also leaves Metal3 at 76.5%
   while Metal5 is at 37%. The next attempt therefore keeps the 40% utilisation
   area but makes the die square and rebalances GRT upward. The full analysis
   and the ranked strategy list are in `FEATURE_LOADER_DRT_PLAN.md`.
4. **Trimmed analog logic.** The digital-only top will not represent the area or
   timing of the analog switch/ADC output logic. That is accepted for this flow.

## Acceptance criteria

- `git diff -- rtl` is empty at every phase.
- Each of the three macros produces LEF, GDS, LIB and a Verilog netlist.
- Each block completes placement/routing with no setup/hold violations at the
  selected frequency, or the run reports the first failing frequency.
- The top completes placement/routing, DRC and LVS; no setup/hold violations at
  the selected frequency.
- The top has only the flat digital pins listed above; no analog pins.
- `reports/librelane/` contains per-block timing summaries and top reports for
  `in2reg`, `reg2out`, `reg2reg` and `feedthrough`.
- The Makefile can reproduce the whole flow from a clean `physical/build/`.

## Current status

- **Feature loader.** The three-minute probe stopped during ABC mapping.
  A placement-only replay used the feature loader's actual synthesized port
  list, the IHP track grid, and LibreLane's custom placer. With the previous
  3049.215 × 2156.625 µm outline, all 2,592 Metal3 east-edge output pins
  had a minimum pitch of 0.42 µm. On a 2717 × 2717 µm test outline, the
  minimum reached 0.84 µm. Actual global routing and 10 MHz timing remain open.
- **ACTMEM.** The initial probe reached floorplanning, where the original
  power hook matched standard cells as well as SRAMs. A second probe reused
  the pre-PnR checkpoint and completed PDN generation in 41 seconds with
  the SRAM-only hook and the orientation corrected to match the IHP LEF.
  OpenDB confirmed 64 non-overlapping SRAMs with `VDD!` and `VDDARRAY!`
  on `VPWR` and `VSS!` on `VGND`. OpenROAD reported `PDN-0195` via
  removals. Power-grid checks and routing remain open.
- **Scaler group.** The earlier run's Magic DRC and XOR were clean.
  KLayout DRC and 25 MHz slow-corner setup remain open. See
  `physical/reports/librelane/output_scaler_group.md`.
- **Top.** Integration requires all three macro view sets.
