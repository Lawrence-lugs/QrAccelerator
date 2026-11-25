# Synthesis notes

Living record of the Yosys synthesis setup. Update after each run.

## Environment

- Container image: `ghcr.io/lawrence-lugs/lugs-soc/lugs-soc-tools:latest`
- Image digest: `sha256:a02447540b423d09ea5d2f722614eca05db1c280b44899a12e822a6299c7093c`
- Yosys: `0.62 (git sha1 7326bb7d6)`
- sv2v: `d381209`
- PDK: `ihp-sg13g2` under `/foss/pdks`
- Liberty: `/foss/pdks/ihp-sg13g2/libs.ref/sg13g2_stdcell/lib/sg13g2_stdcell_typ_1p20V_25C.lib`
- Top: `qr_acc_top`
- ACTMEM: `ram_2w2r`, blackboxed before `hierarchy`

## Frontend

Default: `auto`, which resolves to **sv2v** for this RTL.

| Frontend | Result | Notes |
|---|---|---|
| slang (`read_slang`) | failed | Yosys reports only `ERROR: Compilation failed`; no source location. The `qracc_pkg.svh` package is passed as a source file. |
| verilog (`read_verilog -sv`) | failed | `rtl/control/qracc_csr.sv:11: syntax error` on `input bus_req_t bus_req_i`; the native frontend does not accept the package typedef in the port list. |
| sv2v + verilog | **works** | Converts the package, structs, and arrays to plain Verilog. Used for every successful run. |

sv2v expands several RTL arrays into registers. That is expected and is why the
generic netlist is large:

- `csr_set`, `terms`, `mem` (ram_2w2r), `staging_register`,
  `output_scale`, `output_shift`, `output_offset`, `output_bias`.

## Generic top

Command:

```
make -C /workspace/physical generic
```

The script runs `synth -run begin:fine`, i.e. `begin` + `coarse`
(`proc`, `opt`, `fsm`, `wreduce`, `peepopt`, `alumacc`, `share`,
`memory -nomap`) and stops before the `fine` stage (`memory_map`, `techmap`,
`abc`).

Result: **exit 0, 6m52s (clean run)**, **80,401 cells** including submodules, 725 MB peak,
10.4 MB netlist at `physical/build/generic/qr_acc_top.v`.

Key counts (including submodules):

| Item | Count |
|---|---|
| cells | 80,401 |
| `$alu` | 4,918 |
| `$macc_v2` | 2,838 |
| `$eq` | 37,822 |
| `$mux` | 17,822 |
| `$adffe` | 1,401 |
| `$adff` | 45 |
| `$dffe` | 1 |
| `$mem_v2` | 1 (32-bit, inside `qracc_controller`) |
| `$dlatch` | **0** |
| `ram_2w2r` | 1 blackbox instance, no internal cells |

The intermediate post-`proc` netlist showed 260 inferred latches (256 in
`twos_to_bipolar`, 2 in `seq_acc`, 1 in `qr_acc_top`, 1 in `qracc_controller`),
but the full coarse flow optimises them away: the current stat contains no
`$dlatch`.

`check` reported **104 problems**. See `generic_check.rpt`. The important ones:

- `qracc_csr`: 32 combinational loops through the `$aldff` that drives
  `bus_resp_o` (`AD -> Q -> bus_resp_o`), plus undriven `cfg_o` bits and
  `csr_rd_data_valid_o`.
- `qracc_controller`: undriven `bus_resp_o[32:1]` and `debug_pc_o[31:0]`.
- `qr_acc_wrapper`: `to_analog_o[0]` has no driver.

## IHP SG13G2 mapping

### Full top: not feasible in the 16 GB container

`ihp_top.ys.in` is kept for reference but is **not wired into the Makefile**.
The coarse top is ~80k cells with wide `$alu`/`$macc_v2` arithmetic.
`techmap` expands those into millions of gates; the `opt` pass after it exceeds
the Docker VM's 16 GB and the container terminates with
`error waiting for container: unexpected EOF` after ~20 minutes.

This is a capacity limit of the current environment, not an RTL syntax error.
The right next step for the full top is LibreLane (hierarchy-aware mapping,
macros, and a larger machine), not a bigger `techmap` invocation.

### Block-level: works

Command:

```
make -C /workspace/physical ihp-blocks
```

Result: exit 0, **4m07s** for six blocks. Each block is mapped from its default
parameters, so these are indicative areas, not the top's exact per-instance
area.

| Block | Cells | Area (µm²) | Notes |
|---|---:|---:|---|
| `output_scaler` | 12,843 | 115,105.57 | one scaler lane; the top has 256 |
| `wsacc_pe` | 8,452 | 76,888.22 | one PE |
| `qracc_csr` | 1,998 | 37,214.33 | 32 `$_ALDFFE_PNN_` left unmapped |
| `wr_controller` | 1,053 | 14,986.83 | |
| `padder` | 1,181 | 9,686.82 | |
| `bipolar_bias_sub` | 521 | 5,651.67 | |

`qracc_csr` contains 32 instances of `$_ALDFFE_PNN_` (one per `bus_resp_o` bit);
the `sg13g2_stdcell` liberty has no direct match for that async-load DFF with
enable, so its area is excluded from the reported number.

The block flow is `synth -run begin:fine` → `techmap` → `dfflibmap` → `abc
-fast -liberty` → `stat -liberty`. Running `dfflibmap` **before** `techmap`
leaves many `$_DFF_*`/`$_SDFF_*` cells unmapped and undercounts area; the
current order is deliberate.

## RTL-caused issues

- `rtl/wsacc/wsacc_pe_cluster.sv:52`: unconditional `$display` in the reset
  branch. Stripped in `synth/elaborate.ys` with `delete t:$print`. RTL owner
  should move it under `ifdef DEBUG`.
- `rtl/control/qracc_csr.sv`: `bus_resp_o` feeds the async-load DFF that
  produces it, creating 32 logic loops. Also `cfg_o` has undriven bits and
  `csr_rd_data_valid_o` is undriven.
- `rtl/control/qracc_controller.sv`: `bus_resp_o[32:1]` and `debug_pc_o[31:0]`
  are undriven.
- `rtl/qr_acc_wrapper.sv`: `to_analog_o[0]` is undriven (the `to_analog_o` struct
  is only partially assigned).
- `output_scaler`'s post-mapping `check` reports `y_o` undriven; this is a
  netlist-alias false positive (`y_o_d` is the same net and the final netlist
  does drive `y_o`).

## Changes made outside `physical/`

None to `rtl/`. Root `AGENTS.md` gained a physical-design section; `.gitignore`
gained negations for `physical/synth/`.
