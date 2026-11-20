# REVIEW — multibit plan consistency

Date: 2026-11-19
Scope: all `PLAN_*` documents that feed the multibit datapath. The canonical
active plan is `docs/agent-plans/PLAN_e2e_rtl_fixes.md`; the others are either
history or sub-plans.

## Resolved decisions (2026-11-19)

These override any older plan text:

1. **FS is fixed at `numRows`.** No per-layer `fs_counts` search.
2. **Chooser policy is the e2e plan's:** fixed FS, search `s`.
3. **Clip budget stays 5%.** The old 1% target is dropped.
4. **Weight order is the current working one:** `channel_minor=False`,
   `kernel.transpose(0, 2, 3, 1)`. The `0,3,2,1` wording in old plans is wrong.
5. Old test filenames are not important.
6. **`s` range is 0..8.** The ADC unit sweep now covers the full range.

## Summary

| plan | declared status | actual consistency | disposition |
|---|---|---|---|
| `PLAN_marp_multibit_prescale.md` | no status | **superseded / never achieved as written** | archive |
| `PLAN_marp_multibit_prescale_detailed.md` | no status | **superseded; one decision was wrong** | archive |
| `PLAN_adc_range_model_correction.md` | "executed (P1,P2,P4)" | **partially achieved; D1/P2/P5 stale** | mark partial/superseded |
| `PLAN_rtl_multibit_verification.md` | "executed" | **substantially achieved**, with stale defaults/paths | executed-historical |
| `PLAN_multibit_postscale_certification.md` | "A complete, B/C mostly" | **mostly achieved; stale §7 and B=1 gap** | close or fold into e2e |
| `PLAN_e2e_rtl_fixes.md` | "proposed" | **active; E1/E2.1/first E3 done, E4/E5 not** | canonical |
| `REPORT_multibit_prescale_rtl.md` | "blocked by dead MAC" | historical; ADC numbers superseded | historical |

## 1. `PLAN_marp_multibit_prescale.md` — not achieved as written

The plan says to create `tests/test_marp_multibit_prescale.py` with an
**exact** pre-shift match. That file does not exist. The live test is
`tests/test_marp_multibit_prestack.py`, which uses the later 1 dB
RTL-vs-model criterion and compares `2*MAC` (post-bias), not raw pre-shift
`accumulator[i]`.

It also says:

```text
channel_minor=True
golden_pre = toeplitz @ matrix.T
```

Both are wrong for the final hardware order. The implemented order is
`channel_minor=False` with `kernel.transpose(0, 2, 3, 1)`.

**Conclusion:** this plan was superseded before its acceptance was met. It
should be marked superseded rather than treated as completed.

## 2. `PLAN_marp_multibit_prescale_detailed.md` — one wrong decision

The detailed plan is closer to what was built, but decision #3 is wrong:

> performs `transpose(0,3,2,1).reshape(O,-1).T` internally

The implemented and verified order is `transpose(0,2,3,1)` with
`channel_minor=False`. The detailed plan's `adc_bits=4` default also does not
match `qlinearconv_pre_scale_mac`, whose default is `adc_bits=32`.

Its "exact match" success metric was not the final gate; the prestack test uses
the 1 dB relative criterion. **Mark superseded by the corrected matrix-order
finding.**

## 3. `PLAN_adc_range_model_correction.md` — partial, and D1 is now reversed

### Achieved

- P1 corrected golden ADC (`adc_quantize`, legacy split) — yes.
- P3 corrected RTL ADC and compile-time legacy branch — yes.
- P4 ablation/prestack rewrites — yes, with changes.
- `binary_cfg=0` for multi-bit signed weights — yes.

### Not achieved as written

- **P2 acceptance says clip ≤1%; the code default is 5%.**
  `infer_adc_config(..., saturation_budget=0.05)`; the tests assert 0.05.
- **P2 says the emitted config records `fs_counts` and `bits`.** The CSR
  config only carries `s`, `binary_cfg`, `weight_bits`, `weight_signed`;
  `fs_counts`/`bits` live only in the Python `adc_config` object.
- **P2 says the chooser searches `(s, fs_counts)`.** The production path now
  fixes `fs=numRows` and searches only `s`. The standalone function still
  supports a search, but that is no longer the hardware decision.
- **D1 says FS is a per-layer flexible parameter.** That was explicitly
  reversed: the current model sets `adcFullScale=numRows` (256) and only
  `s` is runtime. D1 should be marked superseded.
- **P5 docs update is incomplete.** `REPORT_multibit_prescale_rtl.md` still
  says "blocked by dead MAC" and contains the old ADC numbers. The findings do
  say the old numbers are superseded, but the report itself was not rewritten.
- The acceptance checklist is entirely unchecked even though the status says
  executed.

### Additional inconsistency

The plan's §2 says 4 bits cannot exceed ~15 dB under `FS=256`. The current
post-scaler result is **36.086 dB** for B=8 with `FS=256`, `s=4` (LSB 2).
That is because the old table's `s`/LSB choice differs; the plan's absolute
SNR conclusion is stale and should not be quoted as current.

## 4. `PLAN_rtl_multibit_verification.md` — substantially achieved, but historical details

The R1-R5 work is real: dead MAC fixed, ADC rewritten, bias block added,
unit/datapath tests pass, matrix order corrected.

Inconsistencies:

- R2 sets `adcFullScale = 2**numAdcBits` (16). The current realistic default
  is `numRows` (256), with `s<=8`. The plan's default is historical.
- R2 acceptance says `s ∈ 0..6`; the hardware/compiler now allows `s<=8`.
  Unit sweeps still use 0..6, so the tests do not cover the new range end.
- R4 says the new `test_seq_acc_multibit` cases live in `test_rtl.py`; they
  live in `tests/test_rtl_multibit_verify.py`.
- R5's prose says `kernel.transpose(0,3,1,2)`, while its own final conclusion
  (and the code) uses `transpose(0,2,3,1)`. The line is a leftover.
- The checkboxes are all ticked, so the plan is "executed", but its R2 defaults
  are superseded by the later ADC model.

## 5. `PLAN_multibit_postscale_certification.md` — mostly achieved, stale claims

Achieved:

- same-input ONNX reference;
- Python post-scaler golden exact for B=2/4/8;
- B=1/depthwise/matmul golden extended later;
- RTL post-scaler B=2/4/8 passes;
- stale `.npy` fixed;
- Q0.16 scaler and 2x/bias fixed;
- single-node 8/8 after scaler fix.

Still not consistent:

- **§7 still says `test_marp_multibit_postscale[8]` fails at -0.43 dB.** It now
  passes at 36.086 dB. This is the most visibly stale statement.
- Phase B says "add B=1 to the post-scaler matrix." The `test_marp_multibit_postscale`
  matrix is still B=2/4/8; B=1 is covered by the separate binary golden and
  `test_qracc_with_onnx_single_node`, not the post-scaler RTL test.
- A2's proposed `rtl_2x=True` parameter was not implemented; the function
  branches on `weight_bits == 1` instead.
- Phase C's "output packing" check is still only implicit in aggregate SNR,
  not a channel-level check.
- Phase D's B=1 acceptance is not in this plan's test matrix.

**Disposition:** close as "node-level phase complete; e2e moved to
`PLAN_e2e_rtl_fixes.md`", and fix §7.

## 6. `PLAN_e2e_rtl_fixes.md` — canonical, but status is stale

Done:

- E1 golden matrix (conv B=2/4/8, B=1 binary, depthwise, matmul).
- E2.1 ADC full scale = `numRows`, `s<=8`, compiler `s` scaling.
- First E3 chain conv→depthwise.

Not done:

- E2 node matrix rerun after the ADC change (only node 0 / B=2 spot checks).
- E2.2/E2.3/E2.4/E2.5 full node-type and packing/zero-point verification.
- E3 beyond node 1, strided/shape-changing, multibit chain.
- E4 per-node B in `traverse_and_compile_nx_graph`, real intermediate
  activations, final logits/top-1. This is the main missing implementation.
- E5 CI wiring.

Its status should change from **proposed** to **active/partial**, and its truth
table should say node 8/8 is pre-ADC until rerun.

## 7. Cross-plan contradictions to resolve

1. **FS model:** ADC plan D1 says per-layer flexible FS; e2e plan says fixed
   `numRows`. The e2e plan is current.
2. **Chooser:** ADC plan says search `(s, FS)`; production now fixes FS and
   searches `s`. Standalone chooser still searches both, which is fine for
   analysis but must not be described as the hardware policy.
3. **Clip budget:** 1% in the ADC plan, 5% in code/tests.
4. **Matrix order:** two old plans say `transpose(0,3,2,1)` /
   `channel_minor=True`; code and findings say `transpose(0,2,3,1)` /
   `channel_minor=False`.
5. **Test path:** old plan says `test_marp_multibit_prescale.py`; actual is
   `test_marp_multibit_prestack.py`.
6. **`s` limit:** RTL plan says 0..6; current hardware/compiler says 0..8.
7. **Postscale status:** old plan says B=8 fails; current test passes.

## 8. Recommended dispositions

- `PLAN_marp_multibit_prescale*.md`: mark **SUPERSEDED**; keep as history.
- `PLAN_adc_range_model_correction.md`: mark **PARTIAL / SUPERSEDED** for D1,
  P2 FS search, 1% clip, and P5; keep P1/P3/P4 as executed.
- `PLAN_rtl_multibit_verification.md`: keep **EXECUTED**, but add a note that
  R2's `adcFullScale=16` and `s<=6` are historical.
- `PLAN_multibit_postscale_certification.md`: mark **NODE-LEVEL COMPLETE**,
  fix §7, and move B=1/packing/full e2e to the canonical plan.
- `PLAN_e2e_rtl_fixes.md`: mark **ACTIVE**, not proposed; add the verification
  gaps from §6.

The only plans that should be treated as current are
`PLAN_e2e_rtl_fixes.md` (active) and the executed record in
`PLAN_rtl_multibit_verification.md` / `FINDINGS_multibit_prescale.md`.
