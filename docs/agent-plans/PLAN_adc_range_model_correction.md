# PLAN — correct the ADC range model (fixed full scale, `s` zooms toward V_RST)

Status: executed (P1, P2, P4). See §9 for what landed and the measured numbers.
Supersedes the ADC semantics used in `REPORT_multibit_prescale_rtl.md` §3–§5
(which modelled `s` as a digital attenuation). Everything else in that report
(testbench capture, chooser shape, test criterion) still stands.

---

## 1. Reference model (as specified 2026-11-18)

Let `N = numRows` be the number of switch-matrix rows that can conduct, and let
`mbl_value ∈ [-N, +N]` be the summed column count (one conducting row = 1).

| mode | ladder span | `V_RST` | `mbl = 0` maps to | codes reachable by a unipolar partial |
|---|---|---|---|---|
| binary (`binary_cfg=1`) | `[0, VDD]` | `VDD/2` | mid-code (code 0) | `0 … 2^(B-1)-1` (upper half only) |
| bipolar (`binary_cfg=0`) | `[-VDD, +VDD]` | `0` | code 0 | `-2^(B-1) … 2^(B-1)-1` |

`adc_ref_range_shifts = s` halves the span about `V_RST`:

```
span(s) = VDD / 2**s          (binary: V_RST +- VDD/2**(s+1))
LSB(s)  = VDD / (2**B * 2**s)
```

In count units, with `FS` = counts for the half-span at `s = 0`:

```
LSB_counts(bits, s) = FS / 2**(bits - 1 + s)
code                = clamp(round(mbl / LSB_counts), -2**(bits-1), 2**(bits-1)-1)
```

So **`s` buys resolution and costs range; `bits` buys range only.** This is the
inverse of the current implementation.

Analytic consequence (uniform quantiser, `σ` = partial standard deviation):

```
SNR = 20·log10(σ / LSB) + 10.79 dB      →   need  σ/LSB ≈ 5.7 for 25 dB
```

For this layer (27 taps, random int8 weights, seed 0):
`mean = 6.7`, `σ = 2.34`, `max = 20` counts, so `σ/FS = 2.34/N`.

---

## 2. Measured consequences of the corrected model

Binary mode, `B = 8`, `SNR` = raw, `SNR_aff` = after a per-channel gain+offset
fit (what a calibrated scaler absorbs; `inf`/306 dB entries are degenerate fits).

**If `FS = ±27` (the 27 driven rows are the full scale):**

| bits | s | LSB (counts) | clip % | SNR | SNR_aff |
|---|---|---|---|---|---|
| 4 | 0 | 3.38 | 0.00 | 2.9 | 7.1 |
| 4 | 1 | 1.69 | 2.63 | 6.8 | 10.5 |
| 5 | 0 | 1.69 | 0.00 | 7.0 | 10.7 |
| 5 | 1 | 0.84 | 1.05 | 12.8 | 16.4 |
| 6 | 0 | 0.84 | 0.00 | 12.8 | 16.7 |
| 7 | 1 | 0.21 | 0.39 | -11.5 | 25.7 |

**If `FS = ±256` (the wrapper's `numRows = inputElements = 256`, only 27 rows
conducting):**

| bits | s | LSB (counts) | clip % | SNR | SNR_aff |
|---|---|---|---|---|---|
| 4 | 0 | 32.0 | 0.00 | 0.0 | 3.9 |
| 4 | 3 | 4.0 | 0.00 | 2.1 | 6.0 |
| 5 | 3 | 2.0 | 0.00 | 5.1 | 8.3 |
| 6 | 3 | 1.0 | 0.00 | inf | 306 |
| 7 | 3 | 0.5 | 0.00 | 0.0 | 306 |

Two conclusions that drive the rest of the plan:

1. **4 bits cannot reach 25 dB on this layer under either reading** — the
   hard ceiling with an ideal offset is ~15 dB (measured separately), because
   `σ/LSB` is ~1, not ~8.
2. **The `FS` interpretation is not cosmetic** (§7, decision D1): with
   `FS = 256` a 4-bit converter cannot even see a 27-tap partial (LSB = 32
   counts); 6 bits plus `s = 3` is the first usable setting.

### 2b. Bipolar ladder (the chosen configuration, D2)

The switch matrix in bipolar mode makes the column current
`mbl = 2P − A_j`, where `A_j` is the number of lanes whose activation bit `j`
is set. `mbl` is symmetric about 0 (range `[-A_j, +A_j]`), so it uses the whole
ladder, and the shift-add needs one correction:

```
Σ_b sign_b·2**b = -1                      (signed B-bit planes)
MAC = ( Σ_j 2**j Σ_b sign_b 2**b q_{j,b}  −  Σ_j 2**j A_j ) / 2
                     └──── acc ────┘        └── the window's activation sum ──┘
```

i.e. subtract the per-window activation sum and divide by two (the factor 2 is
absorbed by the output scaler). The correction is weight-independent, so it is
one integer subtraction per output window, not per channel.

Measured with `FS = max|mbl| = 18` (per-layer, `B = 8`) - **superseded by §9**: the
reconstruction used here omitted the LSB scaling, so these SNRs are too low (the
qualitative conclusion - that 4 comparators are the binding limit - still holds,
but the real numbers are 23/34/55 dB, and the parity-aligned `fs = 16` wins):

| bits | s | LSB | clip % | SNR | SNR (calibrated) |
|---|---|---|---|---|---|
| 4 | 0 | 2.25 | 0.0 | 5.0 | 15.0 |
| 4 | 1 | 1.12 | 3.7 | 16.0 | 19.0 |
| 5 | 0 | 1.12 | 0.0 | 17.2 | 19.9 |
| 6 | 0 | 0.56 | 0.0 | 2.1 | 25.4 |
| 6 | 1 | 0.28 | 1.8 | -8.1 | 26.3 |

(The raw column is polluted by tie-rounding offsets and by clipping, which the
calibrated column partially absorbs — so the calibrated number is optimistic
once clip % is non-zero. Treat 15-19 dB as the honest 4-bit range.)

**So with 4 comparators the best this layer can do is ≈ 16 dB raw / ≈ 19 dB
calibrated, at `s = 1` with ~3.7 % clipping; 25 dB needs 5-6 bits.**

---

## 3. Where the code diverges (audit list)

1. `rtl/ts_qracc.sv` `maxValue/minValue = ±2**(numAdcBits+s-1)` — grows with
   `s`; should shrink (`±numRows / 2**s` in count terms).
2. `adc_out = mbl_value[s +: numAdcBits]` — coarsens the LSB by `2**s`; should
   refine it by `2**s` (or, equivalently, the ladder span should shrink).
3. The model has no notion of `binary` vs `bipolar` ladder span; it assumes
   `mbl` is already centred, which is only true in bipolar mode.
4. The model never normalises by `numRows`, so its implicit full scale is
   `2**(numAdcBits-1+s)` counts rather than `numRows`.
5. `qracc_marp/compile/compile.py` sets `binary_cfg = 1` for multi-bit signed
   weights, i.e. the unipolar half-ladder case, while the sign is handled
   digitally by negating the MSB plane. This is the configuration whose DC
   offset costs half the codes.
6. `infer_bitplane_adc_range_shifts` (rewritten last pass) inherits the wrong
   `s` direction from the model, so its ranking (s=1 best, s=2 coarser) is
   inverted relative to hardware.
7. `tests/utils.py::quant.adc_quantize` reproduces the same inverted semantics,
   so the golden model is consistent with the RTL model but both disagree with
   silicon.

---

## 4. Change plan

### P1 — corrected reference in the golden model (`qracc_marp/quantization/quant.py`, `tests/utils.py`)

* New `adc_quantize(mbl, bits=4, s=0, fs_counts=numRows, mode="binary")`:
  `lsb = fs_counts / 2**(bits-1+s)`, round-half-up, clamp to the code range,
  with the mode fixing the reachable half of the ladder.
* Keep the previous transfer function as `adc_quantize_legacy(...)` so the
  current ablation numbers stay reproducible, and expose it as
  `adc_mode="per_plane_legacy"`.
* `qlinearconv_pre_scale_mac(..., adc_mode="per_plane", adc_bits, adc_shift,
  fs_counts, adc_mode_ladder="binary")`.
* `qlinearconv_prescale_snr(...)` returns `{exact, model, snr_db, snr_affine_db,
  clip_frac, lsb_counts}`; the affine variant is the number to quote once the
  scaler calibration is in place.

### P2 — chooser (`qracc_marp/compile/stimulus_gen.py`, `compile.py`)

* Search `(s, fs_counts)` at `bits = 4` (the synthesised width) with the
  corrected bipolar quantiser, scoring by SNR under a ≤1 % clip budget; also
  evaluate `bits = 5, 6, 8` and log them as a "what a wider converter would
  buy" preview, never silently applied.
* Return a record `{bits, s, fs_counts, predicted_snr_db, clip_frac, lsb_counts}`
  and log the full candidate table at debug level.
* `compile.py` writes `s` into the CSR as today, emits `binary_cfg = 0` for
  multi-bit signed weights, and records `fs_counts`/`bits` in the emitted
  config. **`bits` and the analog full scale are not CSR fields** — flag any
  per-layer intent in the report rather than pretending it is runtime
  selectable.

### P3 — RTL model (`rtl/ts_qracc.sv`)

* Implement the corrected comparison: `lsb = numRows / 2**(bits-1+s)`,
  `code = clamp(round(mbl/lsb), …)`, saturation flags derived from the same
  span; select binary vs bipolar ladder from `binary_cfg`.
* Keep the legacy behaviour behind `` `ifdef ADC_MODEL_LEGACY `` (default off)
  so the old captures can be reproduced.
* Update the DEBUG section: dump `mbl_value`, `lsb`, `code`, `clip` per column
  for the first window; keep the existing SRAM dumps untouched.
* Behavioural only — no change to the switch matrix, PISO or shift-add tree.
  The dead-MAC issue stays a separate change.

### P4 — tests

* `tests/test_marp_multibit_adc_ablation.py`: rewrite around the corrected
  model; print the bits × `s` table for both `FS` readings and both ladder
  modes; assert (a) `LSB = FS/2**(bits-1+s)`, (b) 4 bits cannot exceed ~15 dB
  on this layer, (c) the chooser picks a configuration inside the clip budget,
  (d) legacy vs corrected differ as expected.
* `tests/test_marp_multibit_prestack.py`: unchanged criterion
  (`|SNR_rtl − SNR_model| ≤ 1 dB`), but the model now consumes the read-back
  `(bits, s, fs_counts, mode)`; keep the xfail keyed on the dead MAC.

### P5 — documents

* Update `REPORT_multibit_prescale_rtl.md` §3–§5 and the numbers table with the
  corrected semantics and the new SNR expectations.
* Add the divergence list (above) to `FINDINGS_multibit_prescale.md` as a new
  finding, and note that `rtl/ts_qracc.sv` now documents the hardware spec.

---

## 5. Ordering

P1 → P2 → P4 (pure numpy, no simulator) → P3 (model) → P4 rerun → P5.
The datapath bug (dead MAC) is explicitly out of scope and blocks only the
final 1 dB certification.

---

## 6. Acceptance criteria

- [ ] `LSB_counts(bits, s) = FS / 2**(bits-1+s)` in code, test and RTL model.
- [ ] Ablation reproduces §2's tables within 0.5 dB.
- [ ] Chooser returns a `(bits, s)` pair with clip ≤ 1 % and its predicted SNR
      logged; on the target layer it must state plainly that 4 bits cannot meet
      a 25 dB target.
- [ ] `s` in the CSR has the corrected meaning; the emitted config records the
      assumed `bits` and `fs_counts`.
- [ ] Prestack test still asserts the 1 dB RTL-vs-model criterion (xfail while
      the MAC is dead).
- [ ] Docs updated; no change to the switch matrix / shift-add tree.

---

## 7. Decisions (resolved 2026-11-18)

**D1 — `FS` is a per-layer flexible parameter.** The compiler sets the full
scale (and `s`) per layer rather than inheriting the array's `numRows`. The
model therefore takes `fs_counts` explicitly, and the chooser may treat it as a
search variable alongside `s` (with the populated row count and `numRows` as the
two natural anchors).

**D2 — switch multi-bit weights to the bipolar ladder, with the bias fix.**
Reference configuration for golden, chooser and RTL model:
`mbl = 2P − A_j`, correction `MAC = (acc − Σ_j 2^j A_j)/2` (§2b). This costs one
integer subtraction per window; the factor 2 is absorbed by the scaler
calibration. Required follow-ups:
* `compile.py` must emit `binary_cfg = 0` for multi-bit signed weights (today it
  emits `1`), and the bias term must be subtracted in the datapath (or in the
  scaler's offset) — decide which during implementation.
* `output_scaler` / `pad_bias_data` gain must absorb the `/2`.

**D3 — the hardware is fixed at 4 comparators.** The golden model still
parameterises `bits` so it can preview 5/6/8-bit converters, but the chooser
optimises `(s, FS)` at `bits = 4` and emits the SNR a wider converter would buy
as a report line. Any `bits > 4` result is advisory only.

## 8. Consequences for the earlier report

`REPORT_multibit_prescale_rtl.md` §3-§5 and the 5.5 dB figure describe the
*legacy* (inverted-`s`) convention. They stay as the record of that pass, but
the numbers are superseded by §2/§2b here. The 1 dB RTL-vs-model criterion, the
capture format and the test scaffolding are unaffected.

---

## 9. Execution log (2026-11-18)

### Landed

| file | change |
|---|---|
| `qracc_marp/quantization/quant.py` | `adc_quantize(partials, adc_bits, shift, fs_counts, mode)` implements the fixed-full-scale ladder (`lsb = fs/2**(bits-1+s)`, round-half-up, `bipolar`/`binary` clamp). The old transfer function is `adc_quantize_legacy`. |
| `qracc_marp/compile/stimulus_gen.py` | `_sample_rows`, `_activation_bit_counts` (`A_j`), `_bipolar_partials` (`mbl = 2P - A_j` + bias), `_reconstruct` (undoes bias and LSB scaling), `infer_adc_config` (searches `s` *and* the full scale, scores by SNR under a 5 % clip budget, returns `bits/s/fs_counts/lsb/clip/snr` plus a wider-ADC preview). `infer_bitplane_adc_range_shifts` is a deprecated wrapper. `_bitplane_partials` reduces weights with `quantize_int8_to_bits` (arithmetic shift + clamp) instead of a low-bit mask. |
| `qracc_marp/compile/compile.py` | uses `infer_adc_config` on the 2-D toeplitz, emits `binary_cfg = 0` for multi-bit weights (bipolar matrix), stores the chosen config in `self.adc_config`. |
| `tests/utils.py` | `adc_mode="per_plane"` implements the fixed-FS model (bipolar/binary, `fs_counts`; `per_plane_legacy` kept); `qlinearconv_prescale_snr` returns `snr_affine_db` and forwards `fs_counts`/`ladder`. |
| `tests/test_marp_multibit_adc_ablation.py` | rewritten: quantiser LSB/span, bipolar-vs-binary, bits x `s` table, golden/chooser agreement, legacy final-clip, chooser policy. |
| `tests/test_marp_multibit_prestack.py` | reads `bits`/`fs_counts` from `u_code.adc_config`; maps the golden into RTL units (`2*MAC + activation sum`, divided by the LSB). Still xfail on the dead MAC. |
| `rtl/ts_qracc.sv` | documentation block only (hardware spec plus the note that the behavioural model still does the inverse). |

### Measured (first MobileNetV2 layer, seed 0, 4 comparators, bipolar ladder)

| B | `s` | `fs` | LSB | clip | SNR | calibrated |
|---|---|---|---|---|---|---|
| 2 | 0 | 16 | 1.0 | 4.2 % | 23.1 dB | 23.2 dB |
| 4 | 0 | 16 | 2.0 | 0.0 % | 34.1 dB | 34.1 dB |
| 8 | 0 | 16 | 2.0 | 0.0 % | 54.9 dB | 54.9 dB |

Two things were learned while validating:

1. **The reconstruction needs the LSB scaling.** `MAC = (lsb*acc - bias)/2`; without the `lsb`
   factor the raw SNR was 10-20 dB too low and only the calibrated number looked sane. Both the
   chooser and the golden were fixed.
2. **Parity alignment is what makes 4 bits work.** `mbl = 2P - A_j` is an integer whose parity is
   shared by every plane of a window, so an LSB of exactly 2 counts (`fs = 2**bits`, `s = 0`)
   makes the rounding almost lossless - `fs = 16` scores ~35 dB better than `fs = peak = 17` at
   B=8. The chooser therefore searches the full scale as well as `s`.

### Deviations / open items

* `fs_counts` is an **analog** parameter (reference full scale), not a CSR field: `compile.py`
  reports it in `self.adc_config`, but hardware cannot switch it at runtime. The `bits` preview
  is advisory for the same reason (silicon is fixed at 4 comparators).
* `node.matrix` is **not** in the toeplitz row order (`toe @ node.matrix` is not the MAC). The
  chooser is statistically unaffected, but the tests now build the golden-ordered matrix
  explicitly. This is an unverified layout assumption in the datapath, exposed only because the
  MAC is dead - recorded as a finding.
* The datapath has no bias subtraction yet: with `binary_cfg = 0` the accumulator holds
  `2*MAC + sum_lanes(x)`. Implementing that subtraction is a separate RTL change.
* `tests/test_marp_multibit_prestack.py` was syntax-checked after the last edits; the xfail
  re-run is pending.

