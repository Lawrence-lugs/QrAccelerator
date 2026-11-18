# REPORT — multi-bit pre-scale: golden model, ADC range selection, RTL verification

Date: 2026-11-18
Branch: `feat/multibit-weights-v3` (base `4cac3af`)
Status: implementation complete; **RTL verification blocked by a pre-existing dead-MAC bug** (see §6).
Nothing in this work has been committed.

Companion documents:

* `FINDINGS_multibit_prescale.md` — the bugs and traps found, with evidence.
* `C:\Users\lafqu\.opencode\plan\PLAN_marp_multibit_prescale_rtl.md` — the plan this follows.

---

## 1. Goal

Certify the multi-bit weight path of the accelerator against an integer golden
model, allowing for the fact that the hardware quantises **each bit-plane partial
sum through a 4-bit flash ADC** before the shift-add:

* extend the golden model so it can emulate that ADC exactly, including the
  settable ADC range shift `adc_ref_range_shifts` (`s`);
* capture the **whole** RTL pre-shift accumulator stream, not two samples;
* assert that the RTL is *near* the golden model, `|SNR_rtl − SNR_model| ≤ 1 dB`
  (bit-exact debugging is explicitly deferred);
* replace the ADC range-shift heuristic with a selection based on signal quality,
  because the old rule was a worst-case no-clipping bound.

---

## 2. What changed

| File | Change |
|---|---|
| `qracc_marp/quantization/quant.py` | new `adc_quantize(partials, adc_bits=4, shift=0)` — single shared implementation of the `ts_qracc` ADC transfer function |
| `tests/utils.py` | `qlinearconv_pre_scale_mac(..., adc_bits=32, weight_bits=8, adc_mode='output', adc_shift=0, unfold=False)` with modes `none` / `output` / `per_plane`; new `qlinearconv_prescale_snr(...)` helper; Verilator build now tries `-j 0` and falls back to the configured `-j 1` |
| `qracc_marp/compile/stimulus_gen.py` | `infer_bitplane_adc_range_shifts` rewritten as an SNR-scored search; new `_bitplane_partials`, `_shift_add`; `infer_optimal_adc_range_shifts` now delegates to it |
| `qracc_marp/compile/compile.py` | chooser is fed the full 2-D toeplitz; `weight_bits` threaded through `get_config_from_mapped_node`; removed a wrong `.T` on `mapped_node.matrix`; added the missing `mapped_matrix_to_bank_writes` import |
| `tb/qracc_top/tb_qracc_top.sv` | runtime-gated capture (`+qr_dbg_mac`): `[DBG cfg]`, `[DBG win]`, `[DBG mac]`, `[DBG probe]` |
| `tests/test_marp_multibit_prestack.py` | rewritten around the new model and capture; asserts the 1 dB criterion, xfails with the RTL reason when the datapath returns zero |
| `tests/test_marp_multibit_adc_ablation.py` | new, pure numpy: ADC bits × range-shift study and chooser regression test |
| `FINDINGS_multibit_prescale.md` | new: seven findings with evidence |

No RTL *datapath* file was modified.

---

## 3. The golden model

`tests/utils.py::qlinearconv_pre_scale_mac` returns the integer accumulator for
one output window per row and one output channel per column,
`p = y*W + x`, **before** the output scale/zero-point and **before** bias.

```
w_toeplitz = kernel.transpose(0,3,1,2).reshape(O,-1)        # (K, O)
planes[b]  = weight_bit_planes(w_toeplitz, B, signed=True)
X          = toeplitzize_input(input, zero_point=x_zp, channel_minor=True)   # (P, K)
```

* `adc_mode='none'` — exact integer MAC (the reference; unchanged, still
  bit-identical to ONNX: `max|diff| = 0`, SNR = inf at B = 8).
* `adc_mode='output'` — the old behaviour: clip the *folded* result to `adc_bits`.
  Kept only so the ablation can quantify it. It is **not** a hardware model.
* `adc_mode='per_plane'` — hardware emulation:

```
for j in 0..7:                      # activation bit, LSB first (PISO order)
    xj  = (X >> j) & 1
    Aj  = xj.sum(axis=1)            # activation count for this bit cycle
    for b in 0..B-1:                # weight plane
        part = xj @ planes[b]                       # 0..~20 here
        mbl  = 2*part - Aj                          # bipolar ladder input
        q    = adc_quantize(mbl, 4, s, fs_counts)   # 4-bit flash ADC
        tree += (q << b) if b < B-1 else -(q << b)  # signed MSB plane
    acc += tree << j                # seq_acc integrates shifted trees
mac = (acc * lsb - Σ_j Aj 2^j) / 2   # lsb = fs_counts / 2**(3+s)
```

* `unfold=True` drops the `−x_zp·Σw_B` term. Required to compare against the RTL,
  because `mapped_node.biases` already carries that fold (with *raw int8* weights)
  and `output_scaler` adds it after the accumulator.

### ADC transfer function (`quant.adc_quantize`)

The hardware has a **fixed full scale**; `numAdcBits` subdivides it and `s`
halves the span towards `V_RST`. That means more bits buy *resolution*, not
range — the opposite of what the earlier behavioural model implemented.

```
lsb      = fs_counts / 2**(bits-1+s)          # fs_counts = full-scale span in counts
code     = floor(part / lsb + 0.5)            # round half up
clip     = [-2**(bits-1), 2**(bits-1)-1]      # bipolar
         | [0, 2**(bits-1)-1]                 # binary (V_RST = mid-rail)
value    = code * lsb
```

`infer_adc_config` searches `s` **and** `fs_counts` (see §4). The pre-2026-11-18
behavioural convention (`adc_out = mbl[s +: numAdcBits]`, i.e. bits buy range and
`s` buys range) is preserved as `adc_quantize_legacy` / `adc_mode="per_plane_legacy"`
for comparison only; it is what produced the 5.5 dB result.

Bipolar partials are fed to the ADC as `mbl = 2P − A_j`, where `A_j` is the
activation count for bit cycle `j`; reconstruction is
`MAC = (Σ_j acc_j·2^j·lsb − Σ_j A_j 2^j) / 2`.

---

## 4. ADC range-shift selection

Old rule (`stimulus_gen.infer_bitplane_adc_range_shifts`):

```
s = max(0, ceil(log2(max_partial + 1)) - (adc_bits - 1))
```

Two defects:

1. it is a worst-case **no-clipping** bound with no error term, so it never trades
   quantisation (which grows as `2^s`) against tolerated saturation — it chose
   `s = 2`, costing ~3 dB versus `s = 1`;
2. it ignores the round-up term; the true safety condition is
   `max_partial + 2**(s-1) <= 2**(adc_bits+s-1) - 1`, otherwise a partial can
   round into code 8 and wrap to −8.

New rule:

* sample up to 32 toeplitz windows (strided) so the statistic is not one window;
* for each `s ∈ 0..min(15, ifmap_bits+weight_bits)`, quantise every bit-plane
  partial with `adc_quantize`, rebuild the MAC, and score
  `SNR = 10·log10(var(exact) / var(exact − rebuilt))`;
* reject an `s` whose clipped fraction exceeds a 1 % budget;
* take the argmax, tie-break to the **smaller** `s` (more headroom).

The search is now `infer_adc_config`: it scores candidate `(s, fs)` pairs, with
`fs` allowed to be any power of two in `{2^2 … 2^11}` plus the observed peak
(filtered to `≥ peak/4`), keeps the 5 % saturation budget, and also reports a
`preview` of what 5/6/8-bit ADCs would do (the hardware is fixed at 4 bits, but
the model can preview).  Tie-break: max SNR, then smaller `s`, then smaller `fs`.
For the target node it selects **`s = 0`, `fs = 16`** (LSB = 2 counts), giving
23.1 / 34.1 / 54.9 dB at B = 2 / 4 / 8 — see §7 and `docs/adc_snr_model.md` for
why those numbers are optimistic.

---

## 5. RTL capture and the test

### Capture (`tb/qracc_top.sv`, enabled by `+qr_dbg_mac`)

```
[DBG cfg] adc_ref_range_shifts=… num_output_channels=… mapped_matrix_offset_x=… output_fmap_dimx=… output_fmap_dimy=…
[DBG win] k=<trow> x=<opix_pos_x> y=<opix_pos_y>          (one per accepted window)
[DBG mac] k=<k> o=<channel> pre=<seq_acc.accumulator> post=<qracc_mac_output>
[DBG probe] t=… trk=… acc=… tree=… mac=… valid=… macen=…
```

* `k` is the accepted-window counter, which is also the golden row index
  `p = y*W + x` (the testbench already validates the activations against
  `toeplitz.index({k, …})`, so the pairing is proven, not assumed).
* `o = lane − mapped_matrix_offset_x`.
* 8192 samples per run (256 windows × 32 channels), contiguous `k`, all rows
  covered exactly once, and `post == pre << s` on every sample.
* Volume: ~8 k lines instead of 2 × 256, and no compile-time `DEBUG` define is
  needed (important: Verilator applies `+define+` in command-line order, so an
  `ifdef DEBUG` block in this testbench is silently dropped).

### Test (`tests/test_marp_multibit_prestack.py`, B ∈ {2, 4, 8})

1. build the node with `weight_bits=B, weight_signed=True`;
2. read `s` back from the CSR (`[DBG cfg]`) and cross-check it against the
   compiler's decision — never re-derive it;
3. `exact = qlinearconv_pre_scale_mac(..., adc_mode='none', unfold=True) << s`;
   `model = qlinearconv_pre_scale_mac(..., adc_mode='per_plane', adc_shift=s)`;
4. assert geometry and coverage, then print and assert
   `|SNR(rtl, exact) − SNR(model, exact)| ≤ 1.0 dB`.

Docstring states the criterion and that bit-exact residual debugging is deferred.

---

## 6. The blocker (pre-existing, not caused by this work)

The RTL MAC returns **zero** for every sample:

* `[DBG mac]`: 8192/8192 samples zero from both `seq_acc.accumulator` and
  `qracc_mac_output`;
* probe: `tree_sum = 0` on every cycle while `mac_en = 1`, although activations
  do arrive (`nz_lanes = 27`, columns at the mapped offset).

Mechanism: `rtl/qr_acc_wrapper.sv:51-103` drives the switch-matrix selects from
the PISO data only when `!(clk && mac_en_i)`; whenever `clk && mac_en_i` it forces
`PSM/NSM → VRST`. With every row reset, `ts_qracc.mbl_value = 0`, the ADC encodes
0 and `shift_add_tree.tree_sum = 0`. The digital model of the analog column never
sees data during the phase the accumulator samples.

Evidence that this is pre-existing:

* `tests/test_marp_rtl.py` could not run at `HEAD` at all — `compile.py:259`
  called `mapped_matrix_to_bank_writes`, which was never imported, so the test
  died with a `NameError` before simulating;
* adding **only** that import to a pristine `HEAD` worktree reproduces the same
  single-node SNR bit for bit: `−2.6265186853832647`, identical to the modified
  tree. The new range-shift selection is therefore neither the cause nor a cure
  (with a dead datapath every `s` scores the same).

Candidate next steps (out of scope here, needs RTL review):

* decide which clock phase is supposed to carry the data and blank the switch
  matrix in the other one (e.g. `mac_en_i && !clk` in the behavioural model);
* or make `ts_qracc` sample the data phase explicitly instead of relying on
  zero-delay combinational ordering.

---

## 7. Measured numbers

Reference: node `/features/features.0/features.0.0/Conv_quant` of
`onnx_models/mbv2_cifar10_int8.onnx`, input `(1,3,32,32)` uint8, weights
`(32,3,3,3)` int8, `x_zp = 120`, stride 2, output `(1,32,16,16)`, seed 0.
Max per-plane partial ≈ 19–20 → 5 bits of range are needed.

Per-plane model vs exact unfolded golden, `adc_bits = 4`, bipolar ladder,
`fs = 16` (LSB = 2 counts), `s = 0`:

| `s`/`fs` | B = 2 | B = 4 | B = 8 | note |
|---|---|---|---|---|
| 0 / 16 | **23.08** | **34.08** | **54.89 dB** | chooser's pick; 4.2 % clip at B=2 |
| 0 / 17 | 15.70 | 14.71 | 14.83 dB | LSB = 2.12 counts, i.e. off the integer grid |
| legacy model | 5.5 | 5.5 | 5.5 dB | old inverted ADC convention, for reference |

At `s = 1` with `fs = 16` the LSB becomes 4 counts and the SNR drops accordingly;
the chooser keeps `s = 0` for every `B`.

**Why the 23/34/55 dB progression is fragile.** The independent-noise model
(each plane's quantisation error independent, MSB dominates) predicts ~13–15 dB
flat in `B`, and that is what stochastic rounding and off-grid LSBs produce
(12.2–13.6 dB and 14.7–15.8 dB respectively). The 23/34/55 dB comes from
*coherent* rounding: the bipolar input `mbl = 2P − A_j` shares `A_j`, hence its
parity, across all weight planes of a bit cycle, so with an LSB of exactly 2
counts every plane rounds identically; the common error maps through the
shift-add as `Σ_b s_b 2^b = −1` (a gain-like term) instead of adding in power.
Signal grows ~6 dB per plane while the error stays ~constant (37 counts), which
is the whole progression. Design consequence: do not rely on 23/34/55 dB — an
integer power-of-two LSB is the degenerate case; ~13–15 dB is the robust
expectation. Full derivation and the dither experiment are in
`docs/adc_snr_model.md`.

*For the record:* the 5.5 dB figure in the first version of this report came from
the legacy ADC convention (bits buy range, `s` buys range, per-partial truncation)
plus two model bugs — a missing LSB scaling in the reconstruction and a wrong
B-bit weight reduction (`w & mask` instead of `quantize_int8_to_bits`). All three
are fixed; the tests assert relations rather than absolute values.

---

## 8. Test status

| Suite | Result |
|---|---|
| `tests/test_marp_multibit_prescale.py` (golden vs ONNX) | 9 passed — exact path bit-identical, B=8 `max|diff| = 0` |
| `tests/test_marp_multibit_adc_ablation.py` (new) | 9 passed |
| `tests/test_marp.py` | green (was 4 failures from the missing import) |
| `tests/test_marp_multibit_prestack.py` | 3 **xfail** with the dead-MAC reason (B=2 re-run after the ADC rework: `s=0`, model 23.2 dB, RTL 0) |
| `tests/test_rtl.py` + `tests/test_marp_rtl.py` | 14 passed, 12 failed, 36 skipped |

All 12 failures are accounted for and none are caused by this work:

* `test_tb_qracc[verilator-False-0-binary|bipolar]` (2) — Verilator compile error
  in `tb/qracc/tb_qracc.sv:131` (`from_sram_rd_data` is not declared for this
  parameterisation); the file is untouched.
* `test_qracc_with_onnx_single_node` (7, −1.87 … −3.07 dB) and
  `test_marp_multibit_node_int8` (3, −3.44 / −1.54 / +0.04 dB, threshold 8 dB) —
  the dead MAC above. The latter had never run because of the `NameError`.

Test hygiene note: `test_marp_multibit_node_int8` hard-codes
`/workspaces/QrAccelerator` for `tests/multibit_ref/*.npy`, so it fails with
`FileNotFoundError` whenever the repo is mounted elsewhere.

---

## 9. Findings summary (details in `FINDINGS_multibit_prescale.md`)

1. RTL MAC returns zero under Verilator — switch-matrix blanking during
   `clk && mac_en_i`; blocking, not fixed.
2. The old golden ADC mode (final clip) was meaningless (0.003–0.137 dB).
3. The ADC convention was inverted relative to the hardware: the behavioural model
   let extra bits buy *range* and used `s` to buy range, whereas the hardware has
   a fixed full scale, subdivides it with `numAdcBits`, and uses `s` to zoom
   towards `V_RST`. Corrected in the model and documented in `rtl/ts_qracc.sv`
   (comment only, no behaviour change).
4. With the corrected model the 4-bit ADC gives 23/34/55 dB at B = 2/4/8 — but
   that is the degenerate integer-LSB case. The robust, MSB-dominated expectation
   is ~13–15 dB, confirmed by stochastic rounding and off-grid LSBs; the dominant
   error is the MSB plane (75–80 % of error power). See `docs/adc_snr_model.md`.
5. The zero-point fold uses raw-int8 weights while the MAC uses `w_B`
   (`mapping/core.py:250`, added later by `output_scaler`): −35.3 dB (B=2),
   −24.3 dB (B=4), −1.4 dB (B=8) if you compare folded values. Verification must
   use the unfolded golden; the fold itself is still wrong for B < 8 and is
   **not** fixed.
6. Testbench/compile traps: `+define+` ordering, the `ifndef VERILATOR` region,
   forced `NOTPLITZTRACK` under Verilator, the `.T` bug, the missing import, the
   `-j 0` fallback, the hard-coded mount path.
7. Regression baseline proving the dead MAC and the drive-by import are
   independent of this change.

---

## 10. Reproduction

```bash
# golden vs ONNX (no simulator)
docker run --rm -v "${PWD}:/workspaces/QrAccelerator" -w /workspaces/QrAccelerator \
  qraccelerator-qracc:latest bash -c \
  "conda run -n ic_dec python -m pytest tests/test_marp_multibit_prescale.py -v --tb=short"

# ADC ablation report (no simulator)
docker run --rm -v "${PWD}:/workspaces/QrAccelerator" -w /workspaces/QrAccelerator \
  qraccelerator-qracc:latest bash -c \
  "conda run -n ic_dec python -m pytest tests/test_marp_multibit_adc_ablation.py -v -s"

# RTL SNR test (currently xfail: zero datapath)
docker run --rm -v "${PWD}:/workspaces/QrAccelerator" -w /workspaces/QrAccelerator \
  qraccelerator-qracc:latest bash -c \
  "conda run -n ic_dec python -m pytest tests/test_marp_multibit_prestack.py --simulator verilator -v -rs"
```

Use the `/workspaces/QrAccelerator` mount path (the compose mount) — several
tests hard-code it.

---

## 11. Not done / next

1. Fix the switch-matrix blanking (finding 1) so the MAC produces data; then the
   prestack test should convert from xfail to a real 1 dB assertion, and the
   `test_marp_rtl.py` SNR suite should become meaningful.
2. Fix the zero-point fold to use `w_B` (finding 5) — changes compiler output for
   every multi-bit layer.
3. `test_tb_qracc` compile error in `tb/qracc/tb_qracc.sv` (2 tests).
4. Then, and only then, attempt bit-exact equality against `seq_acc`.
