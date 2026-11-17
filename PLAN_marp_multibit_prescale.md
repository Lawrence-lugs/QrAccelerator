# Plan: Pre-scaling MAC golden comparison test (multibit weights)

## Goal

Compare the RTL's pre-shift MAC output (raw accumulator before `<< adc_ref_range_shifts` in `rtl/seq_acc.sv:227`) against a numpy-simulated QLinearConv golden model that computes the same pre-scaling MAC values directly through the multi-bit-plane path.

The golden model must **match the ONNX QLinearConv output exactly** despite modelling the multi-bit-plane calculation — this is the simpler success metric, replacing the scale-fitting SNR approach used in `test_marp_multibit_prestack.py`.

## Why

The existing `test_marp_multibit_prestack.py` compares the pre-shift accumulator to the ONNX *final post-scaler* output via least-squares scale fitting. That pipeline-stage mismatch produced negative SNR (-0.3 dB for B=2/4) even though the debug dumps work correctly. A direct pre-scaling golden model avoids the stage mismatch and gives a clean pass/fail.

## Golden model (all in `qracc_marp`, no new library code)

**Inputs** — same random `input_tensor` (uint8, NCHW) that the RTL testbench uses, and the mapped node's weight matrix.

**B=1 (binary):**
```
toeplitz = compute.toeplitzize_input(ifmap, ksize, strides, channel_minor=True)
golden_pre = toeplitz @ matrix.T    # raw int32 dot products, no shift, no scale
```

**B>1 (multibit, shift-add + twos_to_bipolar):**
```
planes = quant.weight_bit_planes(weights_int8, B, signed=True)  # (8, *wshape)
per_plane_dot[b] = toeplitz @ planes[b].flatten()               # one dot per plane
golden_pre = sum(per_plane_dot[b] << b for b in range(B-1))     # planes 0..B-2 positive
golden_pre -= per_plane_dot[B-1] << (B-1)                       # MSB plane negated (twos_to_bipolar)
```

This mirrors `seq_acc.sv`: per-plane MACs gated by `b < weight_bits_cfg`, `shift_add_tree` combines planes with `<< b`, MSB plane sign-corrected by `twos_to_bipolar`.

## Test file — `tests/test_marp_multibit_prescale.py` (new)

- Marker: `needs_verilator`, parametrized `weight_bits = [2, 4, 8]`
- Runs Verilator sim with `QRACC_DEBUG=1` (`+define+DEBUG`) and `+cap_file` runtime plusarg
- Parses pre-shift `accumulator[i]` from `[DBG seq_acc] pre_shift` log lines
- Computes numpy golden from the same random `input_tensor` + mapped node weights
- **Success metric:** exact (or near-exact, allowing for trivial zero-padding) match between golden pre-shift values and RTL pre-shift accumulator values
- PNG scatter via `save_scatter_fig` → `images/png/multibit_prescale_B{n}.png`, gated by `--figures`

## Files to create / modify

| File | Action |
|------|--------|
| `tests/test_marp_multibit_prescale.py` | Create — new pytest test |
| `rtl/seq_acc.sv` | Already has pre-shift debug dump (committed in `330d0fa`) — no change needed |
| `rtl/ts_qracc.sv` | Already has mbl_value debug dump (committed in `330d0fa`) — no change needed |
| `tests/utils.py` | Already fixed UTF-8 log reading (committed in `5a9be55`) — no change needed |

## Existing infrastructure reused (no new dependencies)

- `compute.toeplitzize_input` — `qracc_marp/compile/compute.py:16`
- `quant.weight_bit_planes` — `qracc_marp/quantization/quant.py:339`
- `quant.quantize_int8_to_bits` — `qracc_marp/quantization/quant.py:324`
- `save_scatter_fig` — `tests/utils.py:268`
- `--figures` pytest flag — `tests/conftest.py:57`
- `needs_verilator` skip logic — `tests/conftest.py:124`
- `run_simulation`, `VERILATOR_RUN_PLUSARGS`, `QRACC_DEBUG` — `tests/utils.py`

## Container execution (per AGENTS.md)

Always run inside Docker, never on the host:

```
docker compose run --rm qracc bash -c "conda run -n ic_dec python -m pytest tests/test_marp_multibit_prescale.py -v --figures --simulator verilator"
```

The `qraccelerator-qracc:latest` image already exists locally.

## Open questions (resolve before implementation)

1. **Mapped weight extraction** — the test needs `mapped_bin.weights` for the conv node; confirm `core.NxModelMapping` exposes this for the target node (`/features/features.0/features.0.0/Conv_quant`).
2. **Exact vs approximate match** — bit-plane decomposition should be exact integer math; confirm no rounding in the numpy path that would prevent exact ONNX match.
3. **Padding/zero-point handling** — toeplitzize uses `zero_point`; confirm it matches the RTL's padding value (`mapped_node.x_zp`).

---

<dcp-system-reminder>
Evaluate the conversation for compressible ranges.

If any messages are cleanly closed and unlikely to be needed again, use the compress tool on them.
If direction has shifted, compress earlier ranges that are now less relevant.

The goal is to filter noise and distill key information so context accumulation stays under control.
Keep active context uncompressed.

Compressed block context:
- Active compressed blocks in this session: 1 (@b1@)
- If your selected compression range includes any listed block, include each required placeholder exactly once in the summary using `@b1@`.
</dcp-system-reminder>
