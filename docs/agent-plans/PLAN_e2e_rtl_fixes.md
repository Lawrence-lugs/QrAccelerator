# PLAN — end-to-end RTL fixes against the ONNX golden

Status: **proposed.** The node-level post-scaler is certified; this plan closes
the remaining e2e gaps without moving the golden to fit the RTL.

## 0. Ground rules

1. The ONNX output is the reference. `qlinearconv_onnx_reference` runs the
   same node on the **same input** with the hardware's B-bit weights.
2. `qlinearconv_post_scale_mac` is the Python model of the RTL contract. It
   must match ONNX before it is allowed to judge RTL.
3. Never tune the golden to match a broken RTL result. A change is valid only
   if the RTL moves toward ONNX.
4. Every fix gets a test that fails before and passes after.

Current truth table:

| case | status |
|---|---|
| Python post-scale model vs ONNX, B=2/4/8 | **exact, RMSE 0** |
| RTL conv node, B=2 | **62.690 dB** |
| RTL conv node, B=4 | **38.491 dB** |
| RTL conv node, B=8 | **36.086 dB** |
| Binary single-node matrix, 8 nodes | **8/8 passed** (scaler sign fix) |
| Depthwise PE unit tests | **3/3 exact** |
| B=1 binary post-scale golden | **exact, RMSE 0** |
| Depthwise post-scale golden | **exact, RMSE 0** |
| Final matmul post-scale golden | **exact, max diff <= 1** |
| Binary chain conv -> depthwise | **stage0 21.3 dB, stage1 34.9 dB** |
| Full multi-node multibit | **not yet certified** |
| ADC full-scale propagation per layer | **deferred until the ADC programmability model is settled** |

## 1. Phase E1 — complete the golden matrix — DONE

`qlinearconv_post_scale_mac` and `qlinearconv_onnx_reference` now cover:

* **B=2/4/8 conv**: exact (RMSE 0)
* **B=1 binary**: exact (0/1 weights, no 2x, raw scale)
* **depthwise**: exact (raw WSAcc kernel, no 2x)
* **final QLinearMatMul**: exact to the int8 rounding boundary (max diff <= 1)

The tests are `test_python_postscale_model_matches_onnx`,
`test_python_postscale_binary_model_matches_onnx`,
`test_python_postscale_depthwise_binary_matches_onnx`, and
`test_python_postscale_matmul_binary_matches_onnx`.

Historical E1 description:

* **B=1**: `qlinearconv_post_scale_mac` needs a binary branch:
  no `2*MAC`, no `2**(8-B)`, `binary_cfg=1`, scaler scale unchanged.
* **depthwise**: model the WSAcc output/scaler; `rtl_publishes_2x` is false.
* **matmul / final nodes**: use `qlinearconv_onnx_reference` where possible;
  for QLinearMatMul use the same B-weight + w_scale rule.
* **adc_mode**: keep `"none"` for exact model checks and `"per_plane"` for
  the RTL comparison; print `adc_config` (`s`, `fs_counts`) in every test.

Acceptance: a pure Python test matrix over `{B=1,2,4,8} × {conv, depthwise,
matmul}` matches ONNX before any simulator run.

## 2. Phase E2 — node-level RTL matrix

For each node type and B, run the existing node harness with the same-input
ONNX reference. This is where the remaining RTL fixes become visible.

Expected fixes, in order of likelihood:

1. **ADC full-scale is not propagated — DEFERRED.** `QrAccNodeCode.config()` sends
   `adc_ref_range_shifts` but not the chooser's `fs_counts`; `ts_qracc` uses
   the `adcFullScale` parameter (default 16).  Measured on the target node:
   B=2/4/8 choose `fs=16`, but **B=1 chooses `fs=23`** while the RTL still uses
   16.  The binary path is therefore being simulated with a different LSB
   (2.875 vs 2.0) than the config assumes.
   Fix: emit `adc_full_scale` with the config, or constrain the chooser to the
   RTL's fixed `2**numAdcBits` and assert equality per layer.
   **Deferred** until the per-ADC programmability schema is settled (it will
   likely become loaded scaler-like data rather than a compile-time parameter).
2. **B=1 compiler branch.** `rtl_publishes_2x` is false and `binary_cfg=1`;
   verify the scaler path does not apply the multibit 2×/`2**(8-B)`.
3. **Depthwise.** No 2×; verify the WSAcc bias/zero-point and output packing
   with the same golden.
4. **Output packing.** `mm_output_aligner` + PISO + bus read order for a
   non-zero `mapped_matrix_offset_x`; check channels, not just aggregate SNR.
5. **Padding / zero point.** `padding_value = x_zp` and `bias_B` re-fold must
   agree for every node, including non-zero `x_zp`.

Acceptance: node-level RTL SNR meets a per-type threshold (conv ≥ 30 dB for
B=8, ≥ 20 dB for B=2/4; depthwise/matmul thresholds set from their golden).

## 3. Phase E3 — chained two-node test

Feed the RTL output of node A into node B, both compiled through MARP, and
compare each stage with ONNX:

```
ONNX A -> ONNX B
RTL  A -> RTL  B
```

This catches errors that a single-node test cannot: output layout, channel
order, signedness, zero point, activation packing, and scaler state.

Acceptance: `RTL_A ≈ ONNX_A`, `RTL_B ≈ ONNX_B`, and the error does not grow
beyond the per-stage budget. This is the first true e2e gate.

Implemented: `tests/test_marp_multibit_postscale.py::test_marp_binary_chain_conv_depthwise`
runs node 0 (conv) and feeds its NHWC RTL output back as NCHW into node 1
(depthwise):

* stage 0 conv: **21.278 dB**
* stage 1 depthwise: **34.890 dB**

This passes; no RTL fix was required for the chain itself.

## 4. Phase E4 — full model

* Compile every node with a per-node `weight_bits` (do not silently use B=8
  for all layers or randomize to binary).
* Carry `adc_config`, `scale`, and `bias_B` per node.
* Compare final logits / top-1 against ONNX on the same input.
* Only then run the full MBV2 accuracy check.

Expected RTL fixes if E3 passes but E4 fails:

* per-layer `weight_bits` selection and weight reduction in the compiler;
* `adc_ref_range_shifts` / `adcFullScale` per layer;
* output-zero-point and int8 saturation at the model boundary;
* matmul/final-layer path (currently the binary model only).

Acceptance: final output SNR and top-1 delta stated explicitly; no regression
in `test_seq_acc`, `test_rtl_multibit_verify`, prestack, postscale, or WSAcc.

## 5. Phase E5 — regression lock

Add these to the standard verilator gate:

* `test_python_postscale_model_matches_onnx` (no simulator, exact)
* `test_marp_multibit_postscale` B=2/4/8
* `test_marp_multibit_node_int8` B=2/4/8 (same-input ONNX)
* the new chained test
* `test_qracc_with_onnx_single_node` 8/8
* `test_wsacc_dw*`

## 6. What not to do

* Do not change `qlinearconv_onnx_reference` to make RTL pass.
* Do not hide the 2× in an unstated test scale; it belongs to the compiler
  (`scale * 2**(8-B) / 2`, `bias * 2`).
* Do not reuse the old fixed-image `.npy` files.
* Do not certify e2e from the prestack MAC test; it is pre-scaler only.

## 7. Immediate next action

E1 and the first E3 chain are complete.

1. Extend the chain beyond node 1 (node 0 -> 1 -> 2, then a strided layer) to
   exercise output packing and shape changes.
2. Add B=2/4 multibit chain stages once the per-layer B and ADC config are
   carried through `traverse_and_compile_nx_graph`.
3. Revisit E2.1 ADC full-scale when the loaded per-ADC schema exists.
