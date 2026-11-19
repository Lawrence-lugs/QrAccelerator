# REPORT — multibit datapath: consolidated execution record

Date: 2026-11-18
Status: **RTL datapath fixed and verified**; end-to-end multibit prestack
passes. One pre-existing scaler/node failure and one path-specific test remain
out of scope (see §7). Nothing in this work is committed.

This report consolidates the plans that led to the current state. It is the
single entry point; the older plan/report files remain as historical records
with the caveats in §8.

---

## 1. Plan lineage

| document | role | status now |
|---|---|---|
| `PLAN_marp_multibit_prescale.md` | first pre-scale golden test plan | superseded by the detailed plan |
| `PLAN_marp_multibit_prescale_detailed.md` | golden model + test design; decisions D1–D5 | implemented; one weight-order decision was later corrected (§4.6) |
| `REPORT_multibit_prescale_rtl.md` | first implementation report | §3–§5 numbers use the old ADC convention and are superseded |
| `PLAN_adc_range_model_correction.md` | fixed-full-scale ADC semantics, `s` zooms toward `V_RST`, bipolar ladder | executed; see its §9 and FINDINGS §8 |
| `FINDINGS_multibit_prescale.md` | living findings | §1/§9 marked fixed; §11 is the authoritative root-cause list |
| `PLAN_rtl_multibit_verification.md` | this pass: localise dead MAC, ADC rewrite, bias block, tests, matrix order | executed; §8 checkboxes ticked |
| `docs/CRITIQUE_unsigned_multibit_input_conventions.md` | cleanup hand-off for `xBits`/`xTrits`/sign conventions | open |

---

## 2. Decisions that survived

* **ADC is a fixed-full-scale zoom**: `lsb = adcFullScale / 2**(bits-1+s)`,
  round-half-up, bipolar/binary clamp. `s` buys resolution and costs range;
  `bits` buys range. `adcFullScale` is a power of two.
* **Reference configuration is the bipolar switch matrix** with the bias
  correction: `mbl = 2P - A_j`, `MAC = (lsb*acc - sum_j 2**j A_j)/2`.
* **The RTL publishes `2*MAC`** before the output scaler; the residual factor 2
  is absorbed by scaler calibration.
* **The compiler's matrix is the hardware order**: raw receptive field
  flattened as `(kh, kw, C)` with the channel fastest. This is
  `toeplitzize_input(..., channel_minor=False)` dotted with
  `kernel.transpose(0,2,3,1).reshape(O,-1).T` (i.e. `node.matrix`).
  The previous golden used `channel_minor=True`; the golden was permuted, not
  the compiler.
* **Unsigned multibit activations put all lane bits in the MAC**; the top bit
  is a sign/mode bit only for ternary/signed inputs. `QRACC_INPUT_BITS` stays
  8 for `uint8`; widening the lane to 9 breaks feature-loader byte packing.

---

## 3. Execution summary

| phase | work | outcome |
|---|---|---|
| R1 | reproduce dead MAC, fix wrapper select blanking | selects valid for the whole `mac_en` word; all-zero tree_sum gone |
| R2 | rewrite `ts_qracc` ADC, add `adcFullScale`/`binary_cfg`/`ADC_CODE` | bit-exact vs `quant.adc_quantize` for 4/12 bits, both ladders, s=0..6 |
| R3 | add `bipolar_bias_sub`, subtract bias before output shift | bit-exact vs numpy popcount accumulator for T=1,2,4,7,8 |
| R4 | unit + datapath + end-to-end tests | 18 new unit/datapath cases; prestack 3/3 at 0.001 dB |
| R5 | matrix/activation order | hardware is `channel_minor=False`; golden and chooser corrected |

Additional fixes found while executing R1/R4:

* readiness mask now covers bits `0..T-1` (last stage collision for T=8);
* `twos_to_bipolar` unsigned bypass + `input_trits` formula;
* prestack capture tags are one word ahead, so samples are mapped in MAC/raster
  order and tags prove coverage only.

---

## 4. Root causes (short form)

1. **Dead MAC** — `qr_acc_wrapper` blanked PSM/NSM selects on
   `clk && mac_en_i`; the ADC register sampled exactly then. Fixed to a
   word-level `!mac_en_i` gate.
2. **ADC semantics** — old model widened the window and coarsened the LSB with
   `s`; the hardware zooms toward `V_RST`. Rewritten and unit-tested.
3. **Bipolar bias** — `mbl = 2P - A_j` adds a weight-independent bias; new
   block removes it in lock-step with the MAC.
4. **Unsigned MSB** — the top bit is data for unsigned multibit, not a sign.
   See the critique file; the 9-bit lane attempt broke byte packing.
5. **T=8 pipeline collision** — accepting one cycle early overlapped the next
   word's first shift-add with the previous word's last.
6. **Matrix order** — hardware order is `(kh, kw, C)`; the old golden used
   `(kw, C, kh)`.

Full evidence: `FINDINGS_multibit_prescale.md` §11.

---

## 5. Verified state

Commands are the Docker templates from `AGENTS.md` (`qraccelerator-qracc`,
mount at `/workspace`).

| test | result |
|---|---|
| `tests/test_rtl_multibit_verify.py` | **18 passed** — ADC sweep (4), bias unit (5), seq_acc multibit (9; B=2/4/8, 4/12-bit, signed/unsigned, streaming) |
| `tests/test_rtl.py::test_seq_acc` | **12 passed** — legacy captures with `+define+ADC_MODEL_LEGACY` |
| `tests/test_marp_multibit_prestack.py` | **3 passed** — B=2/4/8, `|SNR_rtl-SNR_model| = 0.001 dB`; B=8 RTL 58.116 dB vs model 58.115 dB |
| `tests/test_marp_multibit_adc_ablation.py` | passed |
| `tests/test_marp_multibit_ref.py` | passed |
| `tests/test_weight_planes.py` | passed |
| `tests/test_marp_multibit_postscale.py::test_python_postscale_model_matches_onnx` | **3 passed** - Python golden vs ONNX exact (RMSE 0) for B=2/4/8 |
| `tests/test_marp_multibit_postscale.py::test_marp_multibit_postscale` | **3 passed** - B=2 62.690 dB, B=4 38.491 dB, B=8 36.086 dB |
| `tests/test_marp_rtl.py::test_marp_multibit_node_int8[2]` | **passed** - B=2 62.690 dB with same-input ONNX reference |

The legacy ADC transfer function is now selected by the **compile-time**
`ADC_MODEL_LEGACY` define, not a parameter. Normal builds (and synthesis) do
not contain it; only the historical `test_seq_acc` parameterisations define it
in their simulator arguments.

---

## 6. Synthesis review of the RTL additions

`ts_qracc` is the behavioural analog test schematic; it is not synthesised.
The table distinguishes it from the datapath.

| file / addition | synthesizable? | review |
|---|---|---|
| `qr_acc_wrapper` word-level select gate | yes | pure combinational mux; clock removed from select data path (good: no clock-as-data) |
| `qr_acc_wrapper` n>4 ADC encoder | elaboration-pruned for `numAdcBits=4` | only the thermometer `casez` exists in the 4-bit build |
| `ts_qracc` corrected ADC model | test schematic only | `$clog2`, 64-bit numerator, variable shifts; behavioural, not for synthesis. `adcFullScale` is a power-of-two parameter |
| `ts_qracc` `ADC_CODE` tap | test tap only | 16-bit/column digital code; not part of the analog interface. Trimmed if unused |
| `ts_qracc` `ADC_MODEL_LEGACY` branch | compile-time only | absent from normal builds; cannot reach synthesis |
| `bipolar_bias_sub` | yes | adders + shift register + one `$countones` tree; signed arithmetic. Popcount is window-wide (one per MAC word), not per column |
| `seq_acc` bias/subtract | yes | `$countones(data_p_i)-$countones(data_n_i)` adder tree; variable output shift `lsb_exp` is a barrel shifter. For 4-bit hardware `lsb_exp = 1-s` (range small); consider constraining `s` to 0..6 and trimming the shifter |
| `seq_acc` `scaled_acc`/`bias_corrected` | yes | wide intermediates (`accumulatorBits+16`) are trimmed by synthesis; for 4-bit hardware a much narrower `accumulatorBits+2` would suffice |
| `twos_to_bipolar` unsigned bypass | yes | one mux per lane |
| `ready_mask = 2**input_trits - 1` | yes | small shifter/decoder; `input_trits <= 8` |
| `qracc_pkg` `qrAccAdcCodeBits` / `ADC_CODE` in `from_analog_t` | package/test interface | digital test-only field; the analog schematic leaves it undriven. Struct got wider; AMS wrappers should connect or ignore it |
| `seq_acc` `adcBits > 4` corrected path | elaboration constant | for the 4-bit hardware the condition is false; only `!binary_cfg && weight_signed_cfg` remains |

### Hardware caveats

* **`lsb < 1` (`s > bits-1`)**: `scaled_acc = acc >>> (lsb_exp)` truncates
  before subtracting the bias. The golden keeps the fractional value. The
  current chooser picks `s=0` (LSB=2) for the target layer, so the certified
  path is exact; a future `s>1` policy should do the correction in a wider
  fixed-point domain (or require integer LSB).
* The bias is one window-wide value (weight-independent); do not replicate it
  per column.
* `ADC_CODE` is not an analog output. Do not route it to the physical column
  interface.

---

## 7. Open / out of scope

* **The MAC is certified; the post-scaler phase is now active.** The 58 dB
  prestack result compares `qracc_mac_output` (`2*MAC`) with `2*exact`; it does
  not exercise `output_scaler`, `output_bias`, the output zero point, or the
  final int8 saturation. See
  `docs/agent-plans/PLAN_multibit_postscale_certification.md`.
* **The initial golden was not ONNX.** `qlinearconv_pre_scale_mac` builds a
  numpy MAC from `mapped_node.kernel` and the same input; the prestack test
  compares two modes of that model against RTL. The ONNX Runtime references
  lived in `test_marp_multibit_ref.py`, and its `.npy` files were generated
  from a **fixed CIFAR image**, while `test_marp_multibit_node_int8` drives a
  random input. That test was therefore never a valid ONNX comparison.
* `test_qracc_with_onnx_single_node` now passes **8/8** after the output-scaler
  sign fix. Nodes 1 and 4 (depthwise/WSAcc) pass at 47.4 dB; node 0 at 21.3 dB.
* The binary ADC chooser bug was fixed: B=1 weights are scored unsigned.
* The absolute `/workspaces/QrAccelerator` paths in
  `test_marp_multibit_node_int8` were replaced with repo-relative paths.
* Post-scaler with a same-input ONNX reference now passes:
  **B=2 62.690 dB**, **B=4 38.491 dB**, **B=8 36.086 dB**.
  The compiler owns the 2x and B-bit-weight calibration:
  `scale * 2**(8-B) / 2`, `bias = 2*(bias_raw - x_zp*sum(q))`.
* The Python golden `qlinearconv_post_scale_mac` matches the same-input ONNX
  reference **exactly** (RMSE 0) for B=2/4/8 with `adc_mode="none"`; the RTL
  numbers above include the per-plane ADC approximation.
* **Analog co-simulation re-fire**: the wrapper no longer blanks selects on
  `clk && mac_en_i`. Any VAMS/analog testbench that assumed a particular clock
  phase for the column sample must be re-timed and re-verified. This is also
  flagged in the `ts_qracc` header.
* **Input convention cleanup**: see
  `docs/CRITIQUE_unsigned_multibit_input_conventions.md`.

---

## 8. Document hygiene

* `REPORT_multibit_prescale_rtl.md` §3–§5 (old `s` direction, 5.5 dB figures)
  are historical. Use FINDINGS §8/§11 for the current ADC numbers.
* `PLAN_marp_multibit_prescale.md` is superseded by the detailed plan.
* `PLAN_marp_multibit_prescale_detailed.md` decision #3
  (`transpose(0,3,2,1)`/`channel_minor=True`) is superseded by §4.6 above.
* `FINDINGS_multibit_prescale.md` is the living findings file; §1 and §9 are
  marked fixed, §11 is the current root-cause/verification section.
* `docs/adc_snr_model.md` remains a useful ADC SNR reference.

---

## 9. Key files touched

RTL: `rtl/qr_acc_wrapper.sv`, `rtl/seq_acc.sv`, `rtl/ts_qracc.sv`,
`rtl/ts_qracc_multibank.sv`, `rtl/twos_to_bipolar.sv`,
`rtl/bipolar_bias_sub.sv` (new), `rtl/qracc_pkg.svh`.

Testbenches: `tb/seq_acc/tb_seq_acc.sv`, `tb/qracc_top/tb_qracc_top.sv`,
`tb/ts_qracc/` (new), `tb/bipolar_bias_sub/` (new), `tb/qracc/tb_qracc.sv`.

Python: `qracc_marp/mapping/core.py`, `qracc_marp/compile/compile.py`,
`tests/utils.py`, `tests/test_rtl.py`, `tests/test_marp_multibit_prestack.py`,
`tests/test_rtl_multibit_verify.py` (new).

Docs: this file, `FINDINGS_multibit_prescale.md` §11, the critique file, and
the ticked plan.
