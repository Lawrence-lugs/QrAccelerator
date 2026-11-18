# PLAN — RTL multi-bit datapath: make it work, then certify it

Status: **executed 2026-11-18** (see §8 checkboxes and
`FINDINGS_multibit_prescale.md` §11 for the root causes). Companion to
`PLAN_adc_range_model_correction.md` (golden/chooser, done) and
`FINDINGS_multibit_prescale.md` (§1 dead MAC, §8 ADC semantics, §9 matrix order,
§10 `seq_acc` works).

---

## 1. Decisions taken (2026-11-18)

| # | decision |
|---|---|
| D1 | Localise the dead MAC by **reproducing it in `tb_seq_acc`** with the `qr_acc_top` config, then bisect. Keep `test_seq_acc` green as the invariant. |
| D2 | Intended analog timing: **drive the column while `mac_en` is high, blank only between words.** The current `clk && mac_en` blanking is the bug. |
| D3 | **Bit-exact at `seq_acc`** (ADC out of the loop) and **SNR (1 dB relative) end-to-end**. |
| D4 | ADC bypass for bit-exact tests by **parameterising `numAdcBits`** (12) with a full scale that makes the LSB exactly 1 count. |
| D5 | Bipolar bias removed by a **dedicated `bipolar_bias_sub` block instantiated inside `seq_acc`**. |
| D6 | **Verify the SRAM matrix row order now** (single-hot experiment). |
| D7 | Done = new multibit tests green; the 12 pre-existing failures stay documented. |

---

## 2. Phase R1 — localise and fix the all-zero MAC

### R1.1 Build the repro
`tests/test_rtl.py::test_seq_acc` already drives `mac_data_i` directly through
`seq_acc -> qr_acc_wrapper -> ts_qracc` and passes. Add a **parametrised case**
that matches the failing top-level configuration:

* `xBits = 8`, `unsigned_acts = 1` (so `input_bits = 9`, `input_trits = 8`),
* `wDimY = 27` populated rows (rest zero), `wDimX = 32`, 8 planes,
* `weight_mode = bipolar`, `weight_bits = 8`, `binary_cfg = 0`,
* `numAdcBits = 12` (see R2) so the ADC cannot be the cause,
* reference = the numpy per-plane integer MAC (`_bitplane_partials` +
  `_reconstruct`, unfolded, no bias subtraction).

If this returns zeros, the fault is in `seq_acc`/wrapper/`ts_qracc` and the small
TB is the bisect vehicle. If it matches, the fault is upstream (plane writes,
`mac_data_i` timing, controller) and the next step is the qr_acc_top probe.

### R1.2 Bisect ladder (stop at the first divergence)
1. one plane only, then all 8 (plane write order / `planeWr` slicing),
2. `binary_cfg = 1` vs `0` (NSM drive, polarity of `data_p/data_n`),
3. blanking removed (D2) — the suspected root cause,
4. `adc_ref_range_shifts = 0` vs `> 0`,
5. 27 rows vs 256 (unused rows must contribute zero: `mem == 0` + `NSM = VRST`).

### R1.3 Fix
In `rtl/qr_acc_wrapper.sv`, replace the `if (clk && mac_en_i)` blanking with a
word-level gate:

```systemverilog
// selects follow the PISO for the whole MAC word; blank only between words
if (!mac_en_i) begin ... VRST ... end else begin ... data_p/data_n ... end
```

Keep the `SELB` complements. Do not touch the PISO/shift logic.
Acceptance: `test_seq_acc` (old and new cases) green, `[DBG mac]` non-zero at
`qr_acc_top`, and `tests/test_rtl.py::test_seq_acc` unchanged for the legacy
configurations.

---

## 3. Phase R2 — RTL ADC model rewrite (`rtl/ts_qracc.sv`)

Implements the spec already documented in the file header:

* new parameters: `numAdcBits` (4), `adcFullScale = 2**numAdcBits`
  (half-span in counts at `s = 0`),
* new input: `binary_cfg` (or `ladder_bipolar`), because the ladder span depends
  on it — today `ts_qracc` only sees `adc_ref_range_shifts`,
* `lsb = adcFullScale >> (numAdcBits - 1 + s)`: when `lsb >= 1` use an integer
  compare/round; when `lsb < 1` (finer than a count) shift the count left. All
  of it is shifts because `adcFullScale` is a power of two,
* `code = clamp(round_half_up(mbl / lsb), -2**(n-1), 2**(n-1)-1)` for bipolar,
  `0 .. 2**(n-1)-1` for binary,
* keep the thermometer decode and `ADC_OUT` format unchanged,
* DEBUG: keep the `mbl_value` dump, add the computed `lsb` and `code`.

Acceptance: a new unit TB (`tb/ts_qracc`) sweeps `mbl`, `s ∈ 0..6`,
`bits ∈ {4,12}`, both ladders, and matches `quant.adc_quantize` **bit-exactly**.

---

## 4. Phase R3 — `bipolar_bias_sub` (new `rtl/bipolar_bias_sub.sv`)

The bipolar matrix makes `mbl = 2P - A_j`, so the accumulator holds
`2*MAC + sum_j 2^j A_j`. `A_j` is the popcount of the lane vector at shift `j`
(`piso_buffer_p_q`), which is already available in `seq_acc`.

* Module: `bipolar_bias_sub #(parameter inputTrits, accumulatorBits)` with
  `clk`, `nrst`, `mac_valid`, `popcount_i`, `valid_o`, `bias_o`.
* Accumulate exactly like the MAC: `bias <= (bias >> 1) + (popcount << (inputTrits-1))`
  on the first stage, `(bias >> 1) + ...` afterwards, so `bias = sum_j 2^j A_j`.
* `seq_acc` subtracts `bias_o` from `accumulator` at `valid_o`, *before* the
  `<< adc_ref_range_shifts` (or after — decide by units; both are `<<s` of the
  same correction, so subtract first).
* The residual `/2` stays: the result is `2*MAC`, absorbed by the output scaler.
  Document it in `output_scaler` and in the emitted config.
* Disabled when `binary_cfg = 1` (then `bias_o = 0`).

Acceptance: unit TB (`tb/bipolar_bias_sub`) vs a numpy popcount reference,
**bit-exact**, all `input_trits`, plus a `seq_acc` bit-exact run with
`binary_cfg = 0`.

---

## 5. Phase R4 — tests

| test | level | reference | criterion |
|---|---|---|---|
| `test_ts_qracc_adc` (new TB `tb/ts_qracc`) | ADC | `quant.adc_quantize` | bit-exact, all `bits/s/ladder` |
| `test_bipolar_bias_sub` (new TB) | bias block | numpy popcount accumulator | bit-exact |
| `test_seq_acc_multibit` (new cases in `test_rtl.py`) | datapath | `_bitplane_partials` + `_reconstruct`, unfolded | bit-exact with `numAdcBits=12`, LSB=1 |
| `test_seq_acc_multibit` (4-bit run) | datapath + ADC | same + `adc_quantize` | bit-exact (the model is exact) |
| `test_marp_multibit_prestack` | end-to-end | golden `per_plane` | `|SNR_rtl - SNR_model| <= 1 dB`, then absolute SNR printed |
| matrix order (§9) | SRAM | single-hot weight | the lit output column matches the golden ordering |

Add the `numAdcBits`/`adcFullScale` parameters to the seq_acc TB argument list
and to the `rtl_file_list` of every test that compiles `ts_qracc`.

---

## 6. Phase R5 — matrix row order (single-hot)

Write a matrix with exactly one non-zero weight (row `r`, column `c`), an
activation with exactly one active lane, and check which `(window, channel)` the
MAC lights up. Compare `mapped_matrix_to_bank_writes` order against
`kernel.transpose(0,3,1,2).reshape(O,-1).T`. Expected outcome: either the orders
agree (then §9 is only about `mapped_node.matrix`) or the compiler needs a
permutation fix — record it either way.

---

## 7. Risks

* Rewriting the wrapper's select gating can break the passing `test_seq_acc`
  configurations — run it after every R1/R3 change.
* `ts_qracc` gains inputs (`binary_cfg`, `adcFullScale`); every instantiation
  (wrapper, unit TBs, `test_seq_acc`, `test_tb_column`) must be updated.
* Bit-exactness with `numAdcBits=12` requires `adcFullScale = 2**11` so
  `lsb = 1`; if the RTL model is wrong, the bit-exact test will fail for the
  right reason — do R2 before R4.
* The datapath may still be wrong in the *analog* sense (settling, current
  polarity); only the digital model is being made consistent here.

---

## 8. Acceptance

- [x] `tb_seq_acc` repro case shows the zero output before the fix and the
      correct MAC after it.
- [x] `tests/test_rtl.py::test_seq_acc` (all existing parameterisations) stays
      green (12 passed; the compile-time `ADC_MODEL_LEGACY` define preserves
      their capture semantics and is absent from normal builds).
- [x] `tb/ts_qracc` bit-exact against `quant.adc_quantize` (4 sweep
      configurations, both ladders, s = 0..6, 4/12 bits).
- [x] `tb/bipolar_bias_sub` bit-exact against the numpy popcount accumulator
      (T = 1, 2, 4, 7, 8).
- [x] `seq_acc` multibit bit-exact with a 12-bit ADC (and with the 4-bit ADC
      against the quantised model), including unsigned `T=8` and streaming.
- [x] `test_marp_multibit_prestack` passes the 1 dB relative criterion (B =
      2/4/8, `|delta| = 0.001 dB`); the RTL is no longer all-zero.
- [x] Matrix order verified and recorded: hardware is
      `toeplitzize_input(..., channel_minor=False)` / `node.matrix`
      `transpose(0,2,3,1)`; the golden was the permuted one.
- [x] `FINDINGS` §1/§9 updated to "fixed" with the root cause.  Remaining
      pre-existing end-to-end failures (e.g. the single-node scaler test) are
      listed as out of scope in FINDINGS §11.
