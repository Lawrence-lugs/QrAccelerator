# ACTMEM 2W2R wrapper for IHP SG13G2

`rtl/memory/ram_2w2r.sv` is the behavioural ACTMEM: a flat byte array with two
write ports and two read ports, 32-bit external and 256-bit internal. The IHP
`sg13g2_sram` library has **no 4-port macro**, so `actmem_2w2r_ihp.sv` builds the
same contract from eight 2-port macros.

## Macro choice

The 2-port macros expose two fully independent read/write ports (`A` and `B`),
each with its own address, data, `MEN`, `WEN`, `REN` and clock. The useful
candidates are:

| Macro | Capacity | Ports | Area (µm²) | Notes |
|---|---:|---:|---:|---|
| `RM_IHPSG13_2P_64x32_c2` | 2 kbit | 2 RW | 52,620.88 | no bit mask / BIST |
| `RM_IHPSG13_2P_256x32_c2_bm_bist` | 8 kbit | 2 RW | 96,266.63 | small/medium depths |
| `RM_IHPSG13_2P_1024x32_c2_bm_bist` | 32 kbit | 2 RW | 264,167.28 | **chosen for 256 KiB** |

Eight `256x32` macros form one 256-bit row (8 x 32 bits). One row bank is 8 KiB
of physical memory. The default RTL depth is 256 bytes, which uses only 8 of the
256 rows per macro; that is deliberate because the default exists to keep
synthesis fast, not because it is the final size. The same eight macros cover
any depth up to 8 KiB, and larger depths add macro row banks.

For the physical flow's **256 KiB**, the wrapper uses
`RM_IHPSG13_2P_1024x32_c2_bm_bist`: eight column banks x eight row banks =
**64 macros**, 16,906,705.92 µm² of macro area. The wrapper selects the macro
with the `MACRO_ROWS` parameter (256 or 1024).

No OpenRAM macro is needed for this step.

## Architecture

```
                    8 banks x 32 bits = 256-bit row
  port 1 (32b) ---> bank mux (one bank)
  port 2 (256b) --> all 8 banks, word-rotated

  bank b:  RM_IHPSG13_2P_256x32
             A port = write (port 1 or port 2)
             B port = read  (port 1 or port 2)
```

Address mapping for byte address `A`:

- word index `W = A[..:2]`
- bank `b = W[2:0]`
- macro row `r = W[..:3]`
- a 256-bit access at `A` covers words `W .. W+7`; word `k` goes to
  bank `(W+k) mod 8`, row `(W+k) / 8`
- port 1 accesses one bank; both ports require 4-byte-aligned addresses

The 256-bit port therefore works at any 4-byte boundary, not only at 32-byte
boundaries. The eight words rotate across banks and can span two macro rows.

## Byte order

The wrapper reproduces `ram_2w2r.sv` exactly:

- port 1 is big-endian inside the 32-bit word (`M[A]=D1[31:24]`, ...)
- port 2 writes little-endian (`M[A+i]=D2[8i+:8]`)
- port 2 reads the 32-byte block byte-reversed (`D2[8i+:8]=M[A+31-i]`)

The last item is asymmetric in the behavioural RTL. It is intentional here
because the wrapper must be a drop-in replacement for the golden model. If that
reversal is ever judged a bug, change `ram_2w2r.sv` and this wrapper together.

## Arbitration

`qracc_controller.sv` makes external and internal accesses mutually exclusive:

- `S_LOADACTS` drives `activation_buffer_ext_wr_en` (port 1 write)
- `S_READACTS` drives `activation_buffer_ext_rd_en` (port 1 read)
- `S_COMPUTE_ANALOG` / `S_COMPUTE_DIGITAL` drive `activation_buffer_int_rd_en`
  and `activation_buffer_int_wr_en` (port 2)

The wrapper therefore uses a priority mux (port 2 wins if both are asserted) and
has no ready/stall path. Port 2 read and write use the macro's separate `B` and
`A` ports and can run in the same cycle. A simultaneous port-2 read and write to
the same bank row is not guaranteed by the macro datasheet (it has no conflict
handling); the controller reads the ifmap and writes the ofmap, which are
disjoint regions. The behavioural model matched the golden model in the
same-row tests, but do not rely on that.

If the controller phases ever overlap, this wrapper must grow a real arbiter
with ready/stall signalling (and the ACTMEM port contract must carry it).

## Reset

The SRAM macro has no reset. The wrapper holds `rd_data_1_o` and `rd_data_2_o` at
zero until the first read, then follows the macro output. This matches the
behavioural model's reset behaviour without adding a cycle of latency.

## Files

| File | Role |
|---|---|
| `actmem_2w2r_ihp.sv` | synthesizable banked wrapper; `MACRO_ROWS` selects 256 or 1024 |
| `ram_2w2r_ihp.sv` | physical `ram_2w2r` module used by the physical flow; fixes `MACRO_ROWS=1024` |
| `ihp_sram_2p_256x32_bb.v` | Yosys blackbox view of the 256x32 macro |
| `ihp_sram_2p_1024x32_bb.v` | Yosys blackbox view of the 1024x32 macro |
| `tb_actmem_2w2r.sv` | self-checking testbench against `ram_2w2r` |

## Verification

From the repository root, inside the physical container:

```bash
# one depth (default 256)
make -C /workspace/physical actmem-sim ACTMEM_DEPTH=256

# the three small configurations
make -C /workspace/physical actmem-sweep

# the 256 KiB physical configuration (64 x 1024x32 macros)
make -C /workspace/physical actmem-sim-256k

# Yosys elaboration/stat with the macro blackboxed
make -C /workspace/physical actmem-check ACTMEM_DEPTH=256

# map the wrapper logic to IHP stdcells and print area (macro area is manual)
make -C /workspace/physical actmem-area ACTMEM_DEPTH=256
```

Results:

| Depth | Macros | Simulation |
|---:|---:|---|
| 256 B | 8 | PASS |
| 8 KiB | 8 | PASS |
| 16 KiB | 16 | PASS |
| 256 KiB | 64 | PASS |

Yosys, depth 256: **144 local cells** plus **8 macro blackboxes**, 5,731 wire
bits; `check -assert` reports **0 problems**. Depth 8 KiB: 8 macros. Depth
16 KiB: 16 macros (two row banks).

Macro area, from the IHP datasheet:

- 8 x 96,266.63 = **770,133.04 µm²** (8 KiB configuration)
- 16 x 96,266.63 = **1,540,266.08 µm²** (16 KiB configuration)
- 64 x 264,167.28 = **16,906,705.92 µm²** (256 KiB configuration)

Mapped wrapper logic (`sg13g2_stdcell_typ_1p20V_25C.lib`, `stat -liberty`):
**36,487.47 µm²**, 2,774 standard cells and 8 macro blackboxes at depth 256.
Total for the 8 KiB configuration is therefore about **806,621 µm²**. The
wrapper logic is small relative to the macro array.

## Integration

The current top still blackboxes `ram_2w2r` (see `synth/elaborate.ys`). To use
this wrapper, replace that instance under `MODEL_MEM` in `rtl/qr_acc_top.sv` and
pass `depth = globalBufferDepth`. That is an RTL change and is not part of this
directory. The port list is identical, so the replacement is mechanical.

For synthesis, read `ihp_sram_2p_256x32_bb.v` before the wrapper. The macro is a
hard block; do not synthesize the PDK behavioural model.

PDK views for the macro (from
`/foss/pdks/ihp-sg13g2/libs.ref/sg13g2_sram`):

| View | Path |
|---|---|
| Verilog | `verilog/RM_IHPSG13_2P_256x32_c2_bm_bist.v` |
| LEF | `lef/RM_IHPSG13_2P_256x32_c2_bm_bist.lef` |
| GDS | `gds/RM_IHPSG13_2P_256x32_c2_bm_bist.gds` |
| Liberty | `lib/RM_IHPSG13_2P_256x32_c2_bm_bist_typ_1p20V_25C.lib` |
| Datasheet | `doc/RM_IHPSG13_2P_256x32_c2_bm_bist.txt` |

## Limitations

- `dataSize` must be 8; `interfaceWidth1` must be 32; `interfaceWidth2` must be
  256; `NUM_BANKS` must be a power of two.
- `depth` must be a multiple of 32. Addresses must be 4-byte aligned.
- Port 1 writes whole 32-bit words; there are no byte enables. `ram_2w2r` also
  writes whole words, so this is not a regression.
- No BIST: all macro BIST inputs are tied off.
- Same-bank, same-row port-2 read/write is not guaranteed by the macro datasheet;
  the behavioural model matched in these tests, but the controller must keep the
  ifmap/ofmap regions disjoint.
- The priority mux is not a true arbiter; it relies on the controller's state
  exclusivity described above.

## LibreLane hardening

The 64 SRAM macros are placed on the explicit 8×8 grid in
`physical/librelane/configs/ram_2w2r.yaml`. LibreLane's PDN runs before global
placement, so the locations must be fixed. The memory flow uses
`PDN_MULTILAYER: true` and maps the macro `VDD!`/`VSS!` pins to `VPWR`/`VGND`
through `PDN_MACRO_CONNECTIONS`; the single-layer PDN used by the logic blocks
does not reach the SRAM pins.

Post-global-placement repair is disabled for this block. The 256-bit wrapper
buses made OpenROAD insert about 57k buffers, which then failed detailed
placement. The memory is a hard macro with fixed SRAM locations, so it is
hardened with `SYNTH_STRATEGY: "AREA 3"`, 60% target density and 5% post-CTS
buffer caps.
