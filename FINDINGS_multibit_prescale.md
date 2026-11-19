# Findings — multi-bit pre-scale datapath (2026-11-18)

Scope of this pass: golden model + ADC range-shift selection + the RTL SNR test.
The RTL datapath itself was **not** changed.  Everything below was observed while
building `tests/test_marp_multibit_prestack.py` and
`tests/test_marp_multibit_adc_ablation.py`.

## 1. RTL MAC datapath returns zero under Verilator — **FIXED** (see §11)

**Symptom.** With `B ∈ {2,4,8}`, `s = 1`, node
`/features/features.0/features.0.0/Conv_quant`, the full capture
(`256` windows x `32` channels, `+qr_dbg_mac`) returns **0** for every sample of
both `seq_acc.accumulator` and `qracc_mac_output`.

**Evidence.** One-shot probe (`[DBG probe]`, first window, every cycle):

```
t=0 trk=0000000001 acc=0 tree=0 mac=0 valid=0 macen=1
t=1 trk=0000000010 acc=0 tree=0 mac=0 valid=0 macen=1
...
t=8 trk=0100000010 acc=0 tree=0 mac=0 valid=1 macen=1
```

The activations do arrive (`[DBG seq_acc] event=0 nz_lanes=27 first_lane=192`,
lane 192 = `mapped_matrix_offset_y`, columns at 224..255 =
`mapped_matrix_offset_x`).  `tree_sum` is zero on *every* cycle, including the
cycles where `valid_o` is high, so the accumulator never leaves zero.

**Mechanism.** `rtl/qr_acc_wrapper.sv:51-103` drives the switch-matrix selects
from the PISO data **only when** `!(clk && mac_en_i)`; whenever `clk && mac_en_i`
it forces `PSM_VDR_SEL = PSM_VSS_SEL = 0` and `PSM_VRST_SEL = '1` (same for NSM
in bipolar mode; in `binary_cfg` the NSM is permanently `VRST`).  With all rows
at `VRST`, `ts_qracc.mbl_value = 0`, the flash ADC encodes 0, and
`shift_add_tree.tree_sum = 0`.  So the digital model of the analog column never
sees data during the MAC phase.  This is the same root cause as the earlier
"pre_shift dump is all zeros" observation — it was not a dump-timing problem.

**Next step (out of scope here).** Decide whether the intended behaviour is that
the ADC samples while `clk` is low (i.e. the selects must not be blanked during
`mac_en` in the *digital* model), or whether `ts_qracc` should latch
`mbl_value` on the opposite phase.  Until then no RTL SNR statement is possible.

## 2. The old golden ADC mode was meaningless

`qlinearconv_pre_scale_mac(..., adc_bits=4)` clipped the **final folded** MAC to
`[-8, 7]`.  Measured against the exact MAC on the same input: SNR 0.137 dB
(B=2), 0.041 dB (B=4), 0.003 dB (B=8).  It is now `adc_mode="output"`, kept only
so the ablation test can demonstrate the problem; `adc_mode="none"` is the exact
reference and `adc_mode="per_plane"` is the hardware emulation.

## 3. ADC range-shift heuristic replaced

> **Superseded by §8.** The `s` direction assumed here was inverted; the SNR
> figures below belong to the legacy model and are ~10-20 dB too low.  The
> *shape* of the rule (score candidates by SNR under a saturation budget) is
> what survived.

Old rule: `s = max(0, ceil(log2(max_partial + 1)) - (adc_bits - 1))` — a
worst-case no-clip bound with no error term, and it ignores the `+2**(s-1)`
rounding term (so a partial could round into code `8` and wrap to `-8`).

New rule (`infer_bitplane_adc_range_shifts`): score every `s` by
`SNR(exact, ADC-quantised per-plane reconstruction)` and keep the best, subject
to a 1 % saturation budget, tie-break to the smaller `s`.  For this node it
selects `s = 1` (5.62 dB at 4 bits) instead of `s = 2` (2.28 dB).  A hard
"never saturate" filter was deliberately **not** used: it forces `s = 2`.

Measured table (4-bit ADC, SNR vs exact), `B=2 / 4 / 8`:

| s | B=2 | B=4 | B=8 |
|---|---|---|---|
| 0 | 5.28 | 5.27 | 5.32 dB |
| 1 | 5.65 | 5.53 | 5.55 dB |
| 2 | 2.33 | 2.28 | 2.29 dB |

## 4. The 4-bit ADC, not the weight width, is the limit

> **Superseded by §8** as far as the numbers go (the legacy model had the `s`
> direction inverted).  The qualitative point stands: on this layer the
> comparator count, not `B`, sets the accuracy.

At `s = 1` the 4-bit resolution costs ~5.6 dB regardless of `B`, and going to
5–8 comparators at the same `s` changes nothing (the range shift, i.e. rounding
to multiples of 2, dominates).  `adc_bits = 5..8` with `s = 0` reaches 40–41 dB,
and `>= 6` bits at `s = 0` is exact on this node (no clipping at all, since the
max per-plane partial is 20).  So `adcBits = 4` is the binding constraint; the
range shift cannot recover resolution that the comparator count removed.

Also note `s = 1` uses truncation (`mbl[1 +: 4]`) while `s > 1` rounds half-up,
so `s = 1` carries a systematic `-0.5` bias per partial.  That is why `s = 1`
is only marginally better than `s = 0` here, and why the SNR is not monotone in
`s`.

## 5. Zero-point fold uses different weights than the MAC (not fixed)

`mapped_node.biases` folds `-x_zp * sum(kernel_raw_int8)` (`mapping/core.py`
~250) while the MAC uses the B-bit quantised `w_B`.  For `B < 8` those differ,
and the fold is applied by `output_scaler` (`rtl/output_scaler/output_scaler.sv:71`)
*after* the accumulator.  Measured penalty when comparing a folded RTL result
against the folded golden: -35.3 dB (B=2), -24.3 dB (B=4), -1.4 dB (B=8).

Consequence for verification: the pre-shift accumulator must be compared against
the **unfolded** golden (`unfold=True` in `qlinearconv_pre_scale_mac`), which is
what the RTL test does.

## 6. Testbench/compile traps worth remembering

* Verilator applies `+define+...` in command-line order and `sim_args['verilator']`
  is appended *after* the tb file, so a `` `ifdef DEBUG `` block in
  `tb_qracc_top.sv` is silently dropped (the RTL files listed later do see it).
* `tb_qracc_top.sv:429-430` wraps the task section in
  `` `ifndef POST_SYNTH `` / `` `ifndef VERILATOR ``, so anything added there is
  not compiled for Verilator at all.
* Under Verilator the tb forces `` `define NOTPLITZTRACK `` (line 5-9), so
  `track_toeplitz()` never runs and `display_config()` never prints.  The new
  capture therefore uses a runtime plusarg (`+qr_dbg_mac`) and its own geometry
  print (`[DBG cfg]`).
* `get_config_from_mapped_node()` passed `mapped_node.matrix.T` to the range-shift
  estimator while `mapped_node.matrix` is already `(kernel_elems, out_channels)`;
  that call could not have worked for non-square kernels.  Fixed.
* Verilator builds now try `-j 0` first and fall back to the configured `-j 1`
  build (`tests/utils.py::_run_verilator_simulation`), which cuts wall time
  roughly in half.

## 7. Regression baseline: the dead MAC is pre-existing, the new chooser is not the cause

`tests/test_marp_rtl.py` could not run at `HEAD` at all: `compile.py:259` calls
`mapped_matrix_to_bank_writes`, which was never imported, so
`test_qracc_with_onnx_single_node` dies with a `NameError` before simulating.
After adding only that import to a pristine `HEAD` worktree, node 0 produces

```
RMSE: 22.229971454308597, SNR: -2.6265186853832647
```

i.e. **exactly** the SNR now measured from the modified tree
(`-2.6265186853832647`).  So:

* the failing SNR in `test_qracc_with_onnx_single_node` (`-1.87` … `-3.07 dB`)
  and in `test_marp_multibit_node_int8` is the dead MAC of finding 1, not the
  ADC-range-shift change;
* passing the same node with the old heuristic shows the chooser neither fixes
  nor worsens this (with a dead datapath every `s` scores the same);
* `tests/test_rtl.py::test_tb_qracc` also fails before and after (`tb/qracc/tb_qracc.sv:131`
  uses `from_sram_rd_data`, which is not declared for the parameterisation used;
  the file was not touched by this work).

Consequence: those tests can only go green once the switch-matrix blanking is
resolved, and the `mapped_matrix_to_bank_writes` import is a genuine drive-by fix
that merely unmasks them.

`tests/test_marp_rtl.py::test_marp_multibit_node_int8` (B = 2/4/8) is the same
story: run with the compose mount path it reaches the SNR check and fails at
`-3.44 / -1.54 / +0.04 dB` (threshold 8 dB).  (An earlier run showed
`FileNotFoundError` for `tests/multibit_ref/*.npy` only because the repo was
mounted at `/workspace` while the test hard-codes `/workspaces/QrAccelerator`.)

## 8. The ADC range-shift model was inverted (2026-11-18)

`rtl/ts_qracc.sv` (and the golden model that mirrored it) treated
`adc_ref_range_shifts = s` as a *digital attenuation*: the accepted window grew
to `+/-2**(numAdcBits+s-1)` and the LSB coarsened to `2**s`.  The hardware
description is the opposite - the ladder has a fixed full scale and `s` halves
the span toward `V_RST`, so the LSB gets `2**s` finer and saturation happens
`2**s` counts earlier.  See the comment block in `rtl/ts_qracc.sv` and
`PLAN_adc_range_model_correction.md`.

Consequences that are easy to get wrong:

* **The LSB is `fs_counts / 2**(bits-1+s)`**, and the reconstruction of the MAC
  must rescale by it: `MAC = (lsb * acc - sum_j 2**j A_j) / 2` in bipolar mode.
  Omitting the `lsb` factor costs 10-20 dB of apparent SNR and makes the raw and
  gain-calibrated numbers disagree - which is exactly what happened before the
  fix.
* **`bits` buys range, `s` buys resolution.**  At fixed `s`, adding comparators
  changed nothing in the old model; under the correct model it widens the
  saturation window only.
* **Bipolar mode makes the plane partials symmetric**: `mbl = 2P - A_j`, where
  `A_j` is the number of lanes with activation bit `j` set.  The correction is a
  single subtraction of the window's activation sum (then a factor 2 that the
  scaler absorbs).  `binary_cfg` must therefore be 0 for multi-bit weights.
* **Parity alignment**: `2P - A_j` is an integer whose parity is shared by every
  plane of a window, so an LSB of exactly 2 counts (`fs = 2**numAdcBits`,
  `s = 0`) makes the 4-comparator conversion almost lossless.  On the first
  MobileNetV2 layer that is worth ~35 dB at B = 8 (54.9 dB vs 19.3 dB at
  `fs = 17`).  The chooser searches the full scale as well as `s`.

With that model and 4 comparators the first layer reaches 23.1 / 34.1 / 54.9 dB
for B = 2 / 4 / 8 (calibrated 23.2 / 34.1 / 54.9), against 5.5 dB under the old
convention.

## 9. Matrix / activation order — **RESOLVED** (see §11.6)

`mapped_node.matrix` **is** in the order the hardware feeds to the switch
matrix.  The correct toeplitz is the *raw* receptive field flattened as
`(kh, kw, C)` with the channel fastest, i.e.
`compute.toeplitzize_input(..., channel_minor=False)` dotted with
`kernel.transpose(0, 2, 3, 1).reshape(O, -1).T` (which is what
`_get_matrix_from_kernel` already produced).  The earlier golden used
`channel_minor=True` (`(kw, C, kh)`), so it was the *golden* that was permuted,
not the compiler.  This was confirmed by matching the RTL activation capture
lane-by-lane (events 0..7 equal toeplitz rows 0..7) and the SRAM rows against
`pack_weight_planes`.

## 10. `seq_acc` itself works (the dead MAC is configuration-specific)

`tests/test_rtl.py::test_seq_acc` instantiates the same
`seq_acc -> qr_acc_wrapper -> ts_qracc` chain and **passes**.  So the
accumulator, shift-add tree and ADC models are not fundamentally broken; the
all-zero capture is specific to the `qr_acc_top` configuration (8-bit unsigned
activations, 27 populated rows, `binary_cfg`/multibit, plane write order, or the
phase at which the top-level feeds `mac_data_i`).  Any fix must keep
`test_seq_acc` green - it is the working reference.

## 11. Root causes and fixes (2026-11-18, second pass)

All items below are implemented and verified.

1. **Dead MAC (finding 1).** `qr_acc_wrapper` blanked every PSM/NSM select with
   `clk && mac_en_i`.  The wrapper now selects from `data_p/data_n` for the
   whole MAC word and blanks only when `!mac_en_i` (`rtl/qr_acc_wrapper.sv`).
2. **ADC model (finding 8).** `rtl/ts_qracc.sv` implements the fixed full scale
   (`lsb = adcFullScale / 2**(bits-1+s)`, round-half-up, bipolar/binary clamp)
   and publishes a wide digital `ADC_CODE` tap for `numAdcBits > 4`.  The old
   transfer function is behind the compile-time `ADC_MODEL_LEGACY` define,
   used only by the pre-existing `test_seq_acc` parameterisations so their
   captures stay reproducible.  It is absent from normal builds and
   synthesis.
3. **Bipolar bias.** New `rtl/bipolar_bias_sub.sv` accumulates
   `sum_j 2**j A_j` in lock-step with the MAC.  `seq_acc` publishes
   `(lsb*acc - bias) << s = 2*MAC << s`; the `/2` is absorbed by the scaler.
   It is enabled for signed bipolar weights, disabled for binary/unsigned-1-bit
   paths.
4. **Unsigned multibit MSB.** The top bit is a **sign bit only for ternary
   inputs**; for unsigned multibit it is data.  `twos_to_bipolar` now has an
   `unsigned_acts` bypass (p = value, n = 0), and `seq_acc` uses
   `input_trits = n_input_bits` for unsigned activations (8 for uint8), not
   `n_input_bits + 1 - 1`.  `QRACC_INPUT_BITS` stays 8, so the feature-loader
   byte packing is unchanged.  This was the last blocker for the end-to-end
   test: the prefetch was dropping the bit-7 trit and losing
   `A_7 * 2**7` from the bias and MAC.
5. **Last-stage collision.** `ready_mask` now covers bits `0..T-1`, not
   `0..T-2`.  Accepting one cycle earlier made the next word's first shift-add
   coincide with the previous word's last one for `T=8` (unsigned uint8).
6. **Matrix order (finding 9).** The hardware order is
   `toeplitzize_input(..., channel_minor=False)` = `(kh, kw, C)`, matching
   `node.matrix = kernel.transpose(0, 2, 3, 1).reshape(O, -1).T`.  The golden
   and chooser now use `channel_minor=False`; `_get_matrix_from_kernel` keeps
   `transpose(0,2,3,1)`.  Confirmed by lane-exact activation capture and SRAM
   row comparison.
7. **Capture tags.** `[DBG win]` samples `opix_pos_x/y` one accepted word ahead
   of the MAC it accompanies.  The prestack test maps samples in MAC order
   (which matches activation/toeplitz order) and uses the tags only to prove
   coverage/uniqueness.

### Verification (inside Docker, verilator)

* `tests/test_rtl_multibit_verify.py`: 18 passed (4 ADC sweep cases, 5 bias
  cases, 9 seq_acc multibit cases including unsigned `T=8` and streaming).
* `tests/test_rtl.py::test_seq_acc`: 12 passed (legacy parameterisations,
  `+define+ADC_MODEL_LEGACY`).
* `tests/test_marp_multibit_prestack.py`: 3 passed (B = 2/4/8), with
  `|SNR_rtl - SNR_model| = 0.001 dB` (tolerance 1 dB); the RTL is no longer
  all-zero.
* `tests/test_marp_multibit_adc_ablation.py`, `test_marp_multibit_ref.py`,
  `test_weight_planes.py`: 22 passed.
* `tests/test_marp_rtl.py::test_qracc_with_onnx_single_node[0]` still fails
  (`SNR ≈ -2.4 dB`).  This is a pre-existing end-to-end scaler/node issue, not
  the datapath: the same SNR was measured at `HEAD` in the first pass.  It is
  left as a documented out-of-scope failure (see D7 in
  `PLAN_rtl_multibit_verification.md`).

### 12. Post-scaler and ONNX reference (2026-11-19)

The earlier "one-to-one with ONNX" claim applied only to the pre-output-scale
integer MAC.  `qlinearconv_pre_scale_mac` is a numpy reconstruction from
`mapped_node.kernel`, not an ONNX Runtime call.  The `.npy` references used by
`test_marp_multibit_node_int8` were generated from a fixed CIFAR image while
the test drives a random input, so that test was never a valid ONNX
comparison.

Findings:

1. **Q0.16 scaler sign.** `output_scale` was declared signed; multipliers
   >= 0.5 became negative.  Fixed in `output_scaler_set.sv` /
   `output_scaler.sv`.
2. **2x ownership.** `seq_acc` publishes `2*MAC`.  The compiler now writes
   `scale * 2**(8-B) / 2`, not the raw scale.
3. **B-bit bias.** For B<8 the hardware uses `q = w >> (8-B)`, so the folded
   bias must use `sum(q)`, not `sum(raw kernel)`.  The compiler re-folds it:
   `bias_B = bias_raw - x_zp*sum(q)`, then stores `2*bias_B`.
4. **Real ONNX reference.** `tests/utils.py::qlinearconv_onnx_reference` runs
   ONNX Runtime on the node with the same intermediate input, replaces weights
   with `q`, and multiplies `w_scale` by `2**(8-B)`.
   `qlinearconv_post_scale_mac` models the full scaler contract and matches
   that reference exactly (RMSE 0) for B=2/4/8.

Verification:

* Python golden vs ONNX: exact for B=2/4/8.
* RTL post-scaler: B=2 62.690 dB, B=4 38.491 dB, B=8 36.086 dB.
* `test_qracc_with_onnx_single_node`: 8/8 passed after the scaler fix.
* `test_marp_multibit_node_int8[2]`: 62.690 dB with the same-input ONNX
  reference.
