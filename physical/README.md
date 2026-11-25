# Physical design and synthesis

This directory is the home for everything physical: Yosys synthesis now, and
the LibreLane/OpenLane RTL-to-GDS flow later. It is independent of the
`qraccelerator-qracc` devcontainer image; the synthesis container is derived
from `hpretl/iic-osic-tools` and is pulled from GHCR.

Nothing here edits the RTL. If synthesis exposes an RTL problem, it is recorded
in `reports/synthesis_notes.md` and reported to the RTL owner.

## Layout

```
physical/
  compose.yaml        # compose project qracc-physical (one-off shell service)
  .devcontainer.json  # open the physical/ folder in VS Code with that service
  run.sh              # run a command in the container from the host
  Makefile            # elaborate / generic / ihp / ihp-blocks / actmem-* / checks / clean
  synth/
    rtl.f             # explicit list of files that are elaborated
    elaborate.ys      # hierarchy, ACTMEM blackbox, $print removal
    generic.ys        # technology-independent synth + reports
    ihp_top.ys.in     # full-top IHP mapping (reference only, needs >16 GB)
    synth.sh          # frontend triage + generic/block driver
  actmem/             # 2W2R ACTMEM wrapper around IHP 2-port SRAM macros
  librelane/          # hierarchical LibreLane flow (macros + digital-only top)
  reports/            # tracked text reports (stat, area, notes)
  build/              # ignored: netlists, full logs, generated scripts
```

## Container

`physical/compose.yaml` uses:

- image: `ghcr.io/lawrence-lugs/lugs-soc/lugs-soc-tools:latest`
  (a project image on top of `hpretl/iic-osic-tools:2026.02`)
- image digest used for these results:
  `sha256:a02447540b423d09ea5d2f722614eca05db1c280b44899a12e822a6299c7093c`
- repo root mounted at `/workspace`
- `PDK_ROOT=/foss/pdks`, `PDK=ihp-sg13g2`

It does not use the `qraccelerator-qracc` image, and it does not run the
upstream `start_*.sh` helper scripts. The service overrides the entrypoint with
`/bin/bash` so every command is explicit.

From the repository root:

```powershell
docker pull ghcr.io/lawrence-lugs/lugs-soc/lugs-soc-tools:latest
docker compose -f physical/compose.yaml run --rm --entrypoint /bin/bash qracc-physical -lc "make -C /workspace/physical generic"
```

Or, with the wrapper (Git Bash / WSL):

```bash
./physical/run.sh "make -C /workspace/physical generic"
```

To use VS Code, open the `physical/` folder itself and choose
**Dev Containers: Reopen in Container**. The workspace inside the container is
the repository root (`/workspace`), so `rtl/` remains visible.

## What is synthesised, blackboxed, and excluded

The synthesised top is **`qr_acc_top`**, the maintained digital top used by
`tb/qracc_top/tb_qracc_top.sv`. Its analog bus stays on the top-level ports as
`to_analog_t` / `from_analog_t`.

### Synthesised

| File | Role |
|---|---|
| `rtl/qracc_pkg.svh` | package types and constants |
| `rtl/qr_acc_top.sv` | digital top |
| `rtl/control/qracc_csr.sv` | host-visible CSRs |
| `rtl/control/qracc_controller.sv` | instruction/state controller |
| `rtl/seq_acc.sv` | sequential multibit MAC accumulator |
| `rtl/qr_acc_wrapper.sv` | digital half of one analog column |
| `rtl/wr_controller.sv` | SRAM write/read control |
| `rtl/shift_add_tree.sv` | accumulator adder tree |
| `rtl/twos_to_bipolar.sv` | activation encoding |
| `rtl/bipolar_bias_sub.sv` | window-wide bias correction |
| `rtl/wsacc/wsacc_pe_cluster.sv`, `rtl/wsacc/wsacc_pe.sv` | depthwise weight-stationary array |
| `rtl/feature_loader/feature_loader.sv`, `rtl/feature_loader/padder.sv` | window assembly |
| `rtl/activation_buffer/mm_output_aligner.sv`, `rtl/activation_buffer/piso_write_queue.sv` | output packing |
| `rtl/output_scaler/output_scaler_set.sv`, `rtl/output_scaler/output_scaler.sv` | requantisation |

### Blackboxed

| Module | Why |
|---|---|
| `ram_2w2r` | ACTMEM. Selected by `MODEL_MEM`, which is the configuration every simulation uses. Its ports are kept; its behavioural array is removed with Yosys `blackbox` before `hierarchy`. |

The current top still blackboxes `ram_2w2r`. The IHP implementation is
`physical/actmem/actmem_2w2r_ihp.sv`. It matches the `ram_2w2r` contract:

- 2 write ports, 2 read ports
- port 1: 32-bit wide, port 2: 256-bit wide
- 8-bit data granularity; the IHP wrapper requires 4-byte-aligned port addresses
- `depth` defaults to 256 bytes (2 kbit), but the wrapper scales; see below
- synchronous read, active-low reset on the read outputs

`rtl/memory/ram_2w2r.sv` remains the behavioural reference for that contract.

**Register arrays are not blackboxed.** `feature_loader`'s staging register,
the per-lane scaler registers, the write queues and the WSAcc weight registers
are ordinary flip-flops in the RTL, so Yosys maps them to DFFs. They are not
RAMs and are not the ACTMEM macro. If a future run wants to exclude them, add
explicit `blackbox` lines to `synth/elaborate.ys` (or a dedicated script) and
record the change.

### Excluded (not read by `synth/rtl.f`)

| File / module | Why |
|---|---|
| `rtl/ts_qracc.sv`, `rtl/ts_qracc_multibank.sv`, `rtl/ts_column.sv` | Behavioural models of the analog column and ADC. Testbench-only; `qr_acc_top` has no instance of them. |
| `rtl/column_wrapper.sv` | Testbench image of `qr_acc_wrapper`; not instantiated by the top. |
| `rtl/qr_acc_top_wrapper.sv` | Stale: it declares `qracc_data_interface bus()`, which is defined nowhere in the repo. It cannot elaborate without RTL changes. |
| `rtl/activation_buffer/activation_buffer.sv`, `rtl/activation_buffer/sram_32bank_8b.sv` | The non-`MODEL_MEM` path. `sram_32bank_8b.sv` currently contains only a comment, so this path has no SRAM module. |
| `rtl/memory/ram_1w1r.sv`, `rtl/memory/ram_2w1r.sv`, `rtl/memory/ram_2wr.sv`, `rtl/memory/regfile.sv` | Not instantiated by the top. |
| `rtl/feature_loader/aligned_feature_loader.sv`, `rtl/feature_loader/afl_element.sv` | Not instantiated by the top. |
| `tb/**` | Testbenches. |

## ACTMEM macro

The IHP `sg13g2_sram` library has no 4-port macro. The implementation in
`physical/actmem/` banks eight 32-bit 2-port macros. One macro port is the write
port, the other is the read port; eight banks form a 256-bit row. The wide port
supports any 4-byte boundary, not only 32-byte boundaries, by rotating the eight
32-bit words across banks and rows.

The physical flow's ACTMEM is **256 KiB**: eight column banks x eight row banks
of `RM_IHPSG13_2P_1024x32_c2_bm_bist` = **64 SRAM macros**. The smaller
256×32-macro configurations remain available for the behavioural tests.

| Depth | Macros | Macro area (µm²) | Simulation |
|---:|---:|---:|---|
| 256 B (model default) | 8 × 256x32 | 770,133.04 | PASS |
| 8 KiB | 8 × 256x32 | 770,133.04 | PASS |
| 16 KiB | 16 × 256x32 | 1,540,266.08 | PASS |
| 256 KiB (physical flow) | 64 × 1024x32 | 16,906,705.92 | PASS |

The mapped wrapper logic adds 36,487.47 µm² (2,774 standard cells at depth 256),
so the 8 KiB configuration is about 806,621 µm² total. The 256 KiB area is
dominated by the 64 SRAM macros; its wrapper logic is not separately remapped.
Byte order matches `ram_2w2r` exactly, including the byte-reversed internal-port
read. External and internal accesses are mutually exclusive in
`qracc_controller`, so the wrapper uses a priority mux rather than a ready/stall
arbiter. Port addresses must be 4-byte aligned.

See `actmem/README.md` and `reports/actmem_notes.md` for the architecture,
limitations and integration steps.

## How to run

All commands run inside the container. `make` targets live in `physical/`.

```bash
# technology-independent elaboration + stat only
make -C /workspace/physical elaborate

# generic (technology-independent) synthesis -> build/generic/qr_acc_top.v
make -C /workspace/physical generic

# map one block to IHP SG13G2 (default output_scaler)
make -C /workspace/physical ihp
make -C /workspace/physical ihp BLOCK=wsacc_pe

# map the six small blocks used for the first-pass area table
make -C /workspace/physical ihp-blocks

# both generic and the default block map
make -C /workspace/physical checks

# ACTMEM wrapper: simulate one depth, sweep 256 B / 8 KiB / 16 KiB, or elaborate
make -C /workspace/physical actmem-sim ACTMEM_DEPTH=256
make -C /workspace/physical actmem-sweep
make -C /workspace/physical actmem-check ACTMEM_DEPTH=256
make -C /workspace/physical actmem-area ACTMEM_DEPTH=256

# clean generated outputs
make -C /workspace/physical clean
```

### Frontend selection

`synth.sh` takes `FRONTEND=auto|slang|verilog|sv2v` (default `auto`):

1. `slang` via `read_slang`
2. native Yosys `read_verilog -sv`
3. `sv2v` conversion, then Yosys on plain Verilog

For this RTL, `auto` resolves to **sv2v**:

- slang stops with `ERROR: Compilation failed` (no location).
- native Yosys stops at `rtl/control/qracc_csr.sv:11` on the package typedef in
  the port list.
- sv2v converts the package, structs and arrays successfully.

The winning frontend is recorded in `reports/synthesis_notes.md`; the frontend
logs are in `build/logs/frontend_*.log`.

## First-pass results

### Generic top

- 80,401 cells including submodules, 10.4 MB netlist.
- ~7 min (6m52s clean run).
- ACTMEM: one `ram_2w2r` blackbox instance and no internal cells.
- No `$dlatch` in the final stat (the intermediate post-`proc` netlist had 260).
- 104 `check` problems.

### IHP SG13G2

The full 109k-cell top does **not** map inside the 16 GB Docker VM. `techmap`
expands the wide arithmetic into millions of gates and the container is killed
during the following `opt` pass. `synth/ihp_top.ys.in` is kept for reference
but is not wired into the Makefile.

Block-level mapping is the supported path for now. Default parameters are used
per block, so these areas are indicative:

| Block | Cells | Area (µm²) |
|---|---:|---:|
| `output_scaler` | 12,843 | 115,105.57 |
| `wsacc_pe` | 8,452 | 76,888.22 |
| `qracc_csr` | 1,998 | 37,214.33 |
| `wr_controller` | 1,053 | 14,986.83 |
| `padder` | 1,181 | 9,686.82 |
| `bipolar_bias_sub` | 521 | 5,651.67 |

`qracc_csr` has 32 instances of `$_ALDFFE_PNN_` (one per `bus_resp_o` bit) that
the `sg13g2_stdcell` liberty has no direct match for; their area is excluded.
Full details in `reports/synthesis_notes.md`.

## Reports

Generated by synthesis:

- `reports/generic_stat.rpt` — cell/FF/latch counts for the generic netlist
- `reports/generic_check.rpt` — Yosys `check` output
- `reports/ihp_<block>_area.rpt` — mapped block area
- `reports/ihp_<block>_check.rpt` — post-mapping `check` output

Tracked summaries:

- `reports/synthesis_notes.md` — frontend choice, liberty path, known issues
- `reports/actmem_notes.md` — ACTMEM macro choice, verification and area

Ignored (`build/`): full Yosys logs, generated scripts, netlists.

## Known RTL issues seen by synthesis

- `rtl/wsacc/wsacc_pe_cluster.sv:52` has an unconditional `$display` in the
  reset branch. Yosys turns it into a `$print` cell; `elaborate.ys` removes it
  with `delete t:$print`. This is simulation-only code and should eventually be
  moved under `ifdef DEBUG` by the RTL owner.
- `rtl/twos_to_bipolar.sv`: the intermediate post-`proc` netlist infers 256
  latches (one per lane) from the loop-local `int bit_idx`; `synth` optimises
  them away, so the final coarse stat has no `$dlatch`. Worth re-checking if
  the surrounding logic changes.
- `rtl/control/qracc_csr.sv` has 32 combinational loops through the async-load
  DFF that produces `bus_resp_o`, plus undriven `cfg_o` bits and
  `csr_rd_data_valid_o`.
- `rtl/control/qracc_controller.sv` leaves `bus_resp_o[32:1]` and
  `debug_pc_o[31:0]` undriven.
- `rtl/qr_acc_wrapper.sv` leaves `to_analog_o[0]` undriven.
- `rtl/memory/ram_2w2r.sv` writes port 2 little-endian but reads it back
  byte-reversed. The IHP wrapper reproduces this asymmetry so it stays a drop-in
  replacement; confirm whether the reversal is intentional before changing either.
- `rtl/qracc_pkg.svh` contains `$fwrite`/`string` tasks behind
  `ifdef TRACK_STATISTICS`. Do not define `TRACK_STATISTICS` for synthesis.

## LibreLane hierarchical flow

`physical/librelane/` contains the RTL-to-GDS flow. It hardens the large blocks
into macros, then assembles a digital-only top around them:

| Macro | Source |
|---|---|
| `output_scaler_group` (8 lanes, 32 instances) | `physical/librelane/src/output_scaler_group.sv` |
| `feature_loader` | `rtl/feature_loader/feature_loader.sv` |
| `ram_2w2r` (256 KiB ACTMEM) | `physical/actmem/ram_2w2r_ihp.sv` |

`shift_add_tree` stays in top glue: with 256 outputs it has about 11,000 pins,
which is not a usable hard macro. It is only 6,464 generic cells.

The top is `physical/librelane/src/qr_acc_top_phys.sv`. It exposes only digital
pins and deliberately ties `from_analog` to zero and leaves `to_analog` open so
the first flow is feasible; that is not the final analog interface. The exact
per-field tie counts, the analog-pin budget, and the steps required when the
real analog datapath macros are integrated are documented in
`physical/librelane/README.md`. Read that section before changing the top
wrapper or replacing the ties with the analog macros.

The flow uses LibreLane 3.0.3 from the container and `ihp-sg13g2`. The blocks
started at 50 MHz; the feature loader and scaler group did not close there.
The scaler macro was hardened at 25 MHz (40 ns), but its slow corner still
misses by 2.31 ns. The feature loader is re-hardened at **10 MHz (100 ns)**
because its 25 MHz detailed route plateaued at 1,002,224 violations. The **top
flow targets 10 MHz** with 5% jitter. The 25 MHz scaler views are reused at
10 MHz because the timing arcs are the same and the longer period adds margin.
A 25 MHz scaler signoff would require re-hardening it at a longer period or a
timing ECO. The feature loader is a wide 40% core with data entering
on the left and leaving on the right; the scaler groups are 2:1-tall 65% cores
with data flowing top to bottom. The top is a 65% square. Macros sit on
deterministic grids because LibreLane's PDN runs
before global placement. The top and memory use the full PDN, with
`PDN_MACRO_CONNECTIONS` for the SRAM `VDD!`/`VSS!` pins. Post-CTS buffer
insertion is capped at 5% for setup and hold.
`physical/librelane/DESIGN.md` records the design decisions;
`physical/librelane/Makefile` runs the macro and top stages.
