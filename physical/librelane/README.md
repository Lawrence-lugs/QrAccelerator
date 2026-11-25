# LibreLane physical flow

Hierarchical LibreLane flow for the digital part of `qr_acc_top`. The top is
intended to sit inside a larger SoC, so there is no pad ring. The stand-alone
logic blocks use a single-layer power grid; the memory and top use the full PDN
so the SRAM macro pins are connected.

Design rationale and decisions: `DESIGN.md`.

## Status

First block: `feature_loader`. The whole 256-lane `output_scaler_set` was tried
as one macro first and failed ABC at ~2.57M cells, so the scaler is split into
32 eight-lane `output_scaler_group` macros. The remaining blocks, memory macro
and top are added as each stage is validated. Nothing here edits `rtl/`; all
physical collateral lives under `physical/`.

## Layout

```
physical/librelane/
  DESIGN.md          # approved design and decisions
  Makefile           # preprocess / harden-* / top / report / clean
  configs/           # one LibreLane config per block and for the top
  sdc/               # block and top constraints
  src/               # top wrapper and macro blackbox stubs
  scripts/           # post-flow path-group reports
  runs/              # ignored: LibreLane run directories
```

Generated views go to `physical/build/librelane/macros/<block>/`; tracked
summaries go to `physical/reports/librelane/`.

## Running

From the repository root, inside the physical container:

```bash
# Stop after feature-loader I/O placement and measure the east-edge pin pitch
make -C /workspace/physical/librelane probe-feature

# 8-lane scaler groups (32 macros)
make -C /workspace/physical/librelane harden-scaler-group

# Check the 256 KiB ACTMEM's SRAM placement and PDN
make -C /workspace/physical/librelane probe-ram

# digital-only top, after the three macro view sets exist
make -C /workspace/physical/librelane top
```

`top` runs `check-macros` first and stops with the missing path if any macro
view is absent. The harden, probe, and top targets share a nonblocking lock
and default to a 10-minute wall-clock limit per invocation, including
preprocessing. A timeout terminates the flow and retains its step logs in
`runs/`. Set `FLOW_TIMEOUT=5m` for a shorter iteration. LibreLane uses four
jobs by default (`FLOW_JOBS`).

`probe-feature` tests a square core at 35% utilization with post-GPL design
repair disabled. It keeps the baseline routing derates so the geometry can
be evaluated before any layer tuning. It uses a fresh run tag and checks
the minimum pitch across all 2,592 Metal3 east-edge output pins directly in
the DEF. The pass threshold is 0.84 µm. Set `PROBE_TO=grt` to continue from
that check's explicit checkpoint through global routing within the same
wall-clock limit. To use an existing pin checkpoint, add
`PIN_RUN=<pin-probe-tag>` to the global-routing invocation. That stage requires Metal3 usage at most 65% and zero
global overflow. The probe ends by global routing and publishes no macro
views. `probe-ram` stops after PDN generation, keeping its outputs in the run
directory.

### Logging

OpenROAD block-buffers its stdout when LibreLane pipes it, so a step log can stay
at the first 8 KiB for hours. Run under `stdbuf` and tee the flow output when
live progress matters:

```bash
stdbuf -oL -eL librelane --full ... 2>&1 | tee runs/<tag>.log
```

The detailed-route iteration counts then arrive line by line. Do not interpret a
small `openroad-detailedrouting.log` as an idle router.

Changing the floorplan or pin configuration needs a **new run tag**. Reusing a
tag with `--from` can resume from a later state than requested (for example a
post-CTS netlist that already contains `clknet_*` buffers); running CTS on that
state crashes TritonCTS with `dbNet::get1stSignalInput`.

`shift_add_tree` is not a macro in this flow. With 256 outputs it has about
11,000 pins, which cannot be routed around a small hard macro, so it stays in
top glue. `harden-tree` exists only as an optional experiment.

Or from `physical/librelane`:

```bash
make harden-feature
make harden-scaler-group
```

LibreLane is invoked as `/usr/local/bin/librelane` with `env -u PYTHONPATH`.
The image sets `PYTHONPATH` to miniforge 3.13, while LibreLane 3.0.3 is
installed for system Python 3.12; without the unset it fails on
`_thread.start_joinable_thread`. Use the direct entry point, not
`/foss/tools/bin/librelane`: that wrapper prepends an OpenROAD 2.6 toolchain and
LibreLane 3.0.3's floorplan/STA scripts expect the newer OpenROAD 2.7 already in
the image.

`make fix-librelane` patches the container's bundled
`librelane/scripts/openroad/sta/corner.tcl`: it uses OpenSTA `-fields cap/input`,
while the installed OpenSTA expects `capacitance/input_pin`. The harden targets
depend on this fix.

## Ties in the digital-only top

`physical/librelane/src/qr_acc_top_phys.sv` instantiates `qr_acc_top` with
`globalBufferDepth = 262144` and exposes only digital pins.

### `from_analog` — tied to zero

| Field | Bits per plane | Tie |
|---|---:|---|
| `SA_OUT` | 32 | 0 |
| `ADC_OUT` | 3,840 | 0 |
| `ADC_CODE` | 4,096 | 0 |
| **Total** | **7,968** | 0 |

Eight planes: **63,744 bits tied low**. The digital accumulator therefore sees
zero analog results; this flow is for physical feasibility, not analog function.

### `to_analog` — left open

| Field | Bits per plane |
|---|---:|
| 12 switch-matrix arrays | 3,072 |
| `WL` | 256 |
| `PCH` | 1 |
| `WR_DATA` | 32 |
| `WRITE` | 1 |
| `CSEL` | 32 |
| `SAEN` | 1 |
| `NF`, `NFB`, `M2A`, `M2AB`, `R2A`, `R2AB` | 6 |
| `CLK` | 1 |
| **Total** | **3,402** |

Eight planes: **27,216 bits left open**. Synthesis trims the analog switch/SRAM/
ADC control logic. There is no top-level analog clock pin; `to_analog.CLK` is in
this bus.

### What stays a pin

`bank_select[7:0]` remains a digital output. It selects the analog/SRAM bank and
is constrained as a false path in the first flow.

## Later analog datapath integration

The digital-only top is a flow vehicle, not the final SoC block. When the analog
datapath macros are integrated:

- restore both `to_analog` and `from_analog` on the top;
- remove the `from_analog = '0` tie and do not leave `to_analog` open;
- budget for ~91k analog pins, or partition the interface into smaller macros;
- replace the analog false paths with the real analog timing constraints;
- re-run the full top, not the trimmed digital-only wrapper.

The exact tie code is in `physical/librelane/src/qr_acc_top_phys.sv`.

## Memory path

`MODEL_MEM` stays defined. The physical flow substitutes a new `ram_2w2r`
implementation from `physical/actmem/`, compiled instead of
`rtl/memory/ram_2w2r.sv`. The behavioural model and `qr_acc_top` are untouched.

`activation_buffer` and `sram_32bank_8b` are pre-existing RTL (added in
`a7c2b35` and `7b8d08e`, before this branch) and are not modified.

The physical memory is 256 KiB: 64 × `RM_IHPSG13_2P_1024x32_c2_bm_bist`
(8 row banks × 8 column banks), exact `ram_2w2r` byte semantics, and the
internal-port read reversal preserved.

## Feature-loader address width

`feature_loader` is a 288 x 9-bit register file with 28 write lanes and 288
combinational read outputs. The RTL carries a 32-bit address, although only nine
bits are needed. `src/feature_loader_phys.sv` keeps the 32-bit top-level port,
suppresses writes outside 0..287, and drives a `feature_loader_core` with a
9-bit address (`$clog2(288)`). The generated core is renamed during
`preprocess-feature`; `rtl/` is untouched. The wrapper is a temporary physical
shim: the design RTL should later narrow the address or expose a proper wrapper
abstraction. Shortening the address did not remove the register-file cost,
because the 28 write lanes still need 8,064 address decoders.

## Constraints

- 50 MHz failed the scaler and feature blocks. The scaler macro was hardened at
  25 MHz (40 ns), but its slow corner missed by 2.31 ns. `feature_loader` is
  hardened at 10 MHz (100 ns) because its 25 MHz detailed route plateaued at
  1,002,224 violations. The **top targets 10 MHz**, 5% jitter (5.0 ns), 20% I/O
  (20 ns). The 25 MHz scaler views are reused at 10 MHz
- hold uncertainty is 0.1 ns, not 2.0 ns. Applying the full jitter to hold
  inserted 17,368 hold buffers into the feature loader and hit `RSZ-0060`
- `sg13g2_buf_1` data driver, `sg13g2_buf_16` clock driver,
  `sg13g2_buf_1/A/X` insertion buffer
- `feature_loader` uses a **wide** core (`height/width = 0.7`, about 1.4:1) at
  **40%** util, with data/address pins on the left and the 288 x 9 output bus
  on the right. A 2:1 shape did not leave enough east-edge tracks for 2,592
  outputs. The scaler groups use a **2:1 tall** core (`height/width = 2.0`) at
  65%, with `wx_i` on top and `y_o` on the bottom. The top uses a square die
  packed at 65% target density. The 5.8 mm memory macro is absolute-sized.
- `GRT_ADJUSTMENT: 0.05` for the feature loader. The 15% derate still left
  6,015 overflowed tiles at 40% utilization, mostly on Metal3 and Metal5
- post-GPL design repair is enabled for the feature loader. Without it, the
  post-route slow corner had -43.9 ns setup WNS at 100 ns, on an
  `addr_i` -> flop path with fanout 109/169. Output-port buffering is disabled
  (`DESIGN_REPAIR_BUFFER_OUTPUT_PORTS: false`); buffering all 2,592 `data_o`
  pins made detailed routing much worse. The earlier CTS crash came from
  resuming a contaminated post-CTS state, not from this repair step
- global antenna repair is off for the feature loader (`DIODE_CELL: null`). The
  2,592 east-edge output nets produced 1,271 antenna violations, and the repair
  inserted 214,977 diodes before OpenROAD hit a heap underflow. Fix antenna
  violations when the macro is integrated at the top
- `DRT_THREADS: 32` for the large feature-loader route. The earlier out-of-memory
  failures happened while several LibreLane runs and RTL tests shared the
  15.25 GiB Docker VM; the feature-loader DRT alone peaked near 9 GiB RSS.
  Run at most one PnR flow at a time and do not run RTL simulations alongside it
- macros on deterministic grids: LibreLane's PDN runs before global placement,
  so every macro needs a fixed `instances` location; feature and scaler pins
  use `IO_PIN_ORDER_CFG`, the memory keeps automatic pins
- post-CTS resizer buffer budgets capped at 5% for setup and hold; the default
  50% failed detailed placement on the feature loader
- `RUN_POST_GPL_DESIGN_REPAIR: false` for the memory. The repair inserted
  57,479 buffers before detailed placement failed
- `PDN_MULTILAYER: false` for the logic blocks; `true` for the memory and top,
  with `PDN_MACRO_CONNECTIONS` mapping the SRAM `VDD!`/`VSS!` pins
- path-group reports: `in2reg`, `reg2out`, `reg2reg`, `feedthrough`
