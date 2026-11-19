# PLAN — multibit post-scaler / ONNX end-to-end certification

Status: **Phase A complete, Phase B/C mostly complete.** Supersedes the
"pre-scaler is enough" assumption in `PLAN_rtl_multibit_verification.md`.

Results now in hand:

* `qlinearconv_onnx_reference` is a real ONNX Runtime reference on the same
  input, for B=2/4/8 (weights replaced by `q`, `w_scale` multiplied by
  `2**(8-B)`).
* `qlinearconv_post_scale_mac` is the Python golden for the post-scaler
  contract and matches ONNX **exactly** (`RMSE 0`, SNR inf) for B=2/4/8 with
  `adc_mode="none"`.
* RTL post-scaler: **B=2 62.690 dB**, **B=4 38.491 dB**, **B=8 36.086 dB**.
* `test_marp_multibit_node_int8` now computes the ONNX reference in-test for
  the same random input; B=2 passes at 62.690 dB. The stale `.npy` files are
  no longer used.


## 1. What was actually being compared

`test_marp_multibit_prestack` does **not** compare against ONNX. It calls
`tests/utils.py::qlinearconv_prescale_snr`, which builds two arrays from
`qlinearconv_pre_scale_mac`:

* `exact` — `adc_mode="none"`, `unfold=True`;
* `model` — `adc_mode="per_plane"`, `unfold=True`.

Both start from `mapped_node.kernel` and the same `input_tensor`, use
`toeplitzize_input`, `weight_bit_planes`, and integer shift-add. There is no
ONNX Runtime call in that path. The test asserts

```
| SNR(rtl_post, exact) - SNR(model, exact) | <= 1 dB
```

so it is an RTL-vs-numpy-MAC check, not an RTL-vs-ONNX check.

The ONNX-facing checks are elsewhere:

* `test_marp_multibit_ref.py` uses `onnxruntime` and writes `.npy` references;
* `test_qracc_with_onnx_single_node` uses `QrAccNodeCode.reference_output`
  and the real ONNX model.

And `test_marp_multibit_node_int8` is invalid as written: it loads `.npy`
references generated from `_normalize_cifar(IMAGE_PATH)` (a fixed image), while
the RTL test drives a **random** uint8 tensor. Even a perfect RTL would not
match those files.

## 2. Goal

For the target node (`/features/features.0/features.0.0/Conv_quant`) and
B = 1, 2, 4, 8:

1. the ONNX Runtime output is the reference;
2. the Python post-scaler model and the RTL agree with it;
3. the test fails if the output scaler, bias, zero point, or 2× convention is
   wrong.

## 3. Phase A — golden model

### A1. ONNX reference — implemented

`tests/utils.py::qlinearconv_onnx_reference` now does this (same-input ORT,
B-reduced weights, `w_scale * 2**(8-B)`).  It is used by both the post-scaler
test and `test_marp_multibit_node_int8`.

```python
def qlinearconv_onnx_reference(mapped_node, input_tensor, nx_model=None,
                               weight_bits=None) -> np.ndarray:
    """ONNX Runtime output for this node on exactly this input."""
```

It must:
* run the node (or the full model with an intermediate output) through
  `onnxruntime`;
* use the **same input tensor** as the RTL test;
* optionally substitute B-bit-reduced weights for B<8
  (`quantize_int8_to_bits` then re-scale to int8, as
  `test_marp_multibit_ref.py` does);
* return `(H, W, O)` (NHWC) to match `reference_output` / `hw_ofmap`.

### A2. Post-scaler model — implemented

`tests/utils.py::qlinearconv_post_scale_mac` implements the contract below and
is verified against the ONNX reference by
`test_python_postscale_model_matches_onnx` (exact for B=2/4/8).

```python
def qlinearconv_post_scale_mac(mapped_node, input_tensor, ...,
                               weight_bits=8, adc_mode="per_plane",
                               rtl_2x=True) -> np.ndarray:
    """(2*MAC + bias) * scale + y_zp, rounded and saturated to int8."""
```

It must use the **same** `scale`, `biases`, `y_zp`, and rounding/saturation as
`rtl/output_scaler`. It should be able to run with `rtl_2x=False` so the 2×
question is explicit, not hidden.

### A3. Fix the docstring

`qlinearconv_pre_scale_mac` still says `channel_minor=True` and
`transpose(0,3,1,2)`; the code uses `channel_minor=False` and
`transpose(0,2,3,1)`. Correct the docstring so the golden is not misleading.

## 4. Phase B — tests

* `tests/test_marp_multibit_postscale.py` (new): B=2/4/8, compare RTL
  `hw_ofmap` with `qlinearconv_onnx_reference` for the **same input**.
* `tests/test_marp_multibit_node_int8`:
  * either compute the ORT reference in-test for the same random input, or
  * regenerate `.npy` files with the same input and document the image/seed;
  * remove the fixed-image `.npy` coupling.
* Keep `test_marp_multibit_prestack` as the MAC-level regression, but label it
  explicitly as pre-scaler.
* Add B=1 to the post-scaler matrix (it already passes in
  `test_qracc_with_onnx_single_node`).

## 5. Phase C — RTL / compiler

* **Q0.16 scale is unsigned** — fixed in `output_scaler.sv` /
  `output_scaler_set.sv`; this was the root cause of the bias-only single-node
  failures and of the depthwise failures.
* **2× convention — implemented.** `QrAccNodeCode` owns it:
  `output_scale = mapped_node.scale * 2**(8-B) / 2`,
  `output_bias = 2 * (bias_raw - x_zp*sum(q))`.
* **Bias / zero point — implemented.** `mapped_node.biases` folds
  `-x_zp*sum(raw kernel)`; for B<8 the compiler re-folds with `sum(q)` so the
  hardware accumulator bias matches the B-bit weights.
* **Output packing** — verify `mm_output_aligner` + PISO + bus read order for
  the offset (`mapped_matrix_offset_x=224`) and NHWC.

## 6. Phase D — acceptance

* `test_marp_multibit_postscale`: B=2/4/8 pass at a stated SNR.
* B=8 should be the tightest (int8 exact weights); B=2/4 use the B-reduced ORT
  model, not the raw int8 model.
* `test_qracc_with_onnx_single_node`: all 8 nodes pass (already true after the
  scaler sign fix).
* `test_wsacc_dw.py` / `test_wsacc_dw32.py`: still exact.
* `test_seq_acc`, `test_rtl_multibit_verify`, `test_marp_multibit_prestack`:
  still pass.

## 7. Current evidence

* After the unsigned-Q0.16 fix, `test_qracc_with_onnx_single_node` is **8/8
  passed** (node 0 = 21.3 dB; depthwise nodes 1 and 4 pass).
* `test_marp_multibit_postscale[8]` currently fails at **-0.43 dB** with a
  same-input ONNX reference, so there is a real post-scaler/2×/bias mismatch
  still to fix.
* The prestack B=8 result (58.116 dB) remains valid for the MAC only.

## 8. Files

* `tests/utils.py` — ONNX reference + post-scale model.
* `tests/test_marp_multibit_postscale.py` — end-to-end gate.
* `tests/test_marp_rtl.py` — fix the stale `.npy` test or replace it.
* `qracc_marp/compile/compile.py` / `stimulus_gen.py` — 2× scale ownership,
  scaler data.
* `rtl/output_scaler/*.sv` — Q0.16 and rounding.
* `FINDINGS_multibit_prescale.md` — append the post-scaler findings.
* `docs/FINDINGS_wsacc_depthwise.md` — mark resolved by the scaler fix.
