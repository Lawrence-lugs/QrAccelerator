# ACTMEM 2W2R IHP wrapper notes

## Context

`rtl/memory/ram_2w2r.sv` defines the ACTMEM contract: two write ports, two read
ports, port 1 32-bit, port 2 256-bit, byte-addressable, synchronous read. The
current top uses `depth = globalBufferDepth = 256` bytes by default; that is a
placeholder, not the final memory size.

The IHP `sg13g2_sram` library has **no 4-port macro**. Its 2-port macros have
two independent read/write ports, so the wrapper banks eight of them and uses
one macro port for writes and the other for reads.

## Macro decision

| Macro | Capacity | Ports | Area (µm²) | Decision |
|---|---:|---:|---:|---|
| `RM_IHPSG13_2P_64x32_c2` | 2 kbit | 2 RW | 52,620.88 | not chosen: 8 KiB needs four row banks, 32 macros |
| `RM_IHPSG13_2P_256x32_c2_bm_bist` | 8 kbit | 2 RW | 96,266.63 | small/medium depths |
| `RM_IHPSG13_2P_1024x32_c2_bm_bist` | 32 kbit | 2 RW | 264,167.28 | **chosen for 256 KiB** |

Eight `256x32` macros give one 256-bit row (8 x 32 bits) and 8 KiB of physical
memory. The default 256-byte depth uses 8 of the 256 rows per macro; one row
bank still covers any depth up to 8 KiB, and deeper memories add row banks.

For the physical flow's **256 KiB**, the wrapper uses
`RM_IHPSG13_2P_1024x32_c2_bm_bist`: eight column banks x eight row banks =
**64 macros**, 16,906,705.92 µm² of macro area.

OpenRAM is not needed for this step.

## Wrapper

`physical/actmem/actmem_2w2r_ihp.sv`:

- eight banks; `MACRO_ROWS` selects `RM_IHPSG13_2P_256x32_c2_bm_bist` or
  `RM_IHPSG13_2P_1024x32_c2_bm_bist`
- macro A port = write, B port = read
- 256-bit access uses all eight banks and rotates the eight 32-bit words
- a wide access may start at any 4-byte boundary and may span two macro rows
- port 1 accesses one bank; port 1 and port 2 addresses must be 4-byte aligned
- port 2 wins if external and internal requests overlap; the controller states
  make them mutually exclusive
- port 2 read and write use separate macro ports; same-row conflicts are not
  handled by the macro and are avoided by the controller's ifmap/ofmap split
- read outputs are zero until the first read, matching `ram_2w2r`

Byte order is copied from the behavioural model:

- port 1: big-endian inside the 32-bit word
- port 2 write: little-endian
- port 2 read: byte-reversed 32-byte block

The port-2 read reversal is an asymmetry in `ram_2w2r.sv`. The wrapper
intentionally reproduces it so it is a drop-in replacement. If the RTL is ever
changed, change both together.

`physical/actmem/ram_2w2r_ihp.sv` is the physical `ram_2w2r` module. It has the
same ports and parameters as the behavioural model and fixes `MACRO_ROWS=1024`;
the physical file list uses it instead of `rtl/memory/ram_2w2r.sv`.

## Verification

Commands, all inside the physical container:

```bash
make -C /workspace/physical actmem-sweep
make -C /workspace/physical actmem-sim-256k
make -C /workspace/physical actmem-check ACTMEM_DEPTH=256
```

The testbench drives the wrapper and `ram_2w2r` with identical stimulus and
fails on any mismatch. It covers reset, every 256-bit word, every 32-bit word,
cross-port writes/reads, wide accesses at 4-byte (not 32-byte) boundaries, a
simultaneous port-2 read/write to different rows, and same-row / same-address
port-2 read/write. The IHP behavioural model matched the golden model in the
same-row cases, but the datasheet says the macro has no conflict handling, so
keep the controller's disjoint ifmap/ofmap regions as the real guarantee.

| Depth | Macro instances | Result |
|---:|---:|---|
| 256 B | 8 | PASS |
| 8 KiB | 8 | PASS |
| 16 KiB | 16 | PASS |
| 256 KiB | 64 | PASS |

Yosys `actmem-check`, depth 256, with the macro blackboxed:

- 144 local cells, 5,731 wire bits, 14 ports
- 2 `$adffe`, 39 `$alu`, 14 `$eq`, 17 `$logic_and`, 4 `$logic_not`,
  17 `$logic_or`, 26 `$mux`, 17 `$shiftx`
- 8 `RM_IHPSG13_2P_256x32_c2_bm_bist` blackboxes
- `check -assert`: 0 problems

Depth 8 KiB also gives 8 macros; depth 16 KiB gives 16. The 256 KiB
configuration uses 64 `1024x32` macros (8 column banks x 8 row banks).

## Area

From the IHP datasheet, one `256x32` macro is 136.97 x 702.83 µm =
96,266.63 µm²:

- 8 macros: **770,133.04 µm²**
- 16 macros: **1,540,266.08 µm²**

One `1024x32` macro is 385.37 x 685.49 µm = 264,167.28 µm²; 64 macros
(256 KiB) are **16,906,705.92 µm²**.

Mapped wrapper logic (`sg13g2_stdcell_typ_1p20V_25C.lib`, `stat -liberty`):
**36,487.47 µm²**, 2,774 standard cells plus the 8 macro blackboxes at depth
256. The 8 KiB configuration is therefore about **806,621 µm²** total.

## Constraints and limitations

- `dataSize = 8`, `interfaceWidth1 = 32`, `interfaceWidth2 = 256`
- `depth` is a multiple of 32; addresses are 4-byte aligned
- port 1 writes whole 32-bit words; no byte enables (same as `ram_2w2r`)
- no BIST; macro BIST inputs are tied off
- simultaneous port-2 read/write to the same bank row is undefined
- the priority mux is not a full arbiter; it relies on controller state
  exclusivity (`S_LOADACTS` / `S_READACTS` versus `S_COMPUTE_*`)

## Integration

The current top still blackboxes `ram_2w2r` in `synth/elaborate.ys`. Replacing
it with this wrapper requires an RTL change in `rtl/qr_acc_top.sv` under
`MODEL_MEM`; the port list matches, and `depth = globalBufferDepth` is passed
through. For synthesis, read `ihp_sram_2p_256x32_bb.v` before the wrapper and
keep the macro as a hard blackbox. Do not synthesize the PDK behavioural model.
