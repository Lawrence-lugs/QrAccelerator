# ADC SNR model — reconciling `6.02B + 1.76`, `20·log10(σ/LSB)` and the measured 23 / 34 / 55 dB

Status: reference note, 2026-11-18. Companion to
`PLAN_adc_range_model_correction.md` and `../FINDINGS_multibit_prescale.md`.

## 1. The three numbers that need reconciling

For the first MobileNetV2 layer, 4 comparators, bipolar ladder, `s = 0`:

| weight width | chosen `fs` | LSB (counts) | measured SNR |
|---|---|---|---|
| B = 2 | 16 | 2.0 | 23.1 dB |
| B = 4 | 16 | 2.0 | 34.1 dB |
| B = 8 | 16 | 2.0 | 54.9 dB |

The rule of thumb "4 bits ≈ 25 dB" (`6.02·4 + 1.76 = 25.8`) predicts roughly the
same for all three, and a naive per-plane noise analysis with this layer's
statistics predicts **~13 dB** for all three. Neither matches 23/34/55.
Section 5 explains why, and confirms that the 13 dB / B-independent picture is
the correct one *when the per-plane quantisation errors are independent*.

## 2. One quantiser law, three parameterisations

For a quantiser with step `Δ` (in the same units as the signal) and a signal of
standard deviation `σ`, the error power is `Δ²/12` as long as the error is
approximately uniform and uncorrelated with the signal:

```
SNR = σ² / (Δ²/12) = 10·log10(12) + 20·log10(σ/Δ)
    = 20·log10(σ/Δ) + 10.79 dB
```

Note the additive constant: **10.79**, not 1.76. (An earlier draft of the
ablation docstring quoted `+1.8`; that was wrong.)

**Full-scale sine.** A sine that fills the converter has `σ = FS/(2√2)` and
`Δ = FS/2^B`, so `σ/Δ = 2^(B-1)/√2` and

```
SNR = 20·log10(2^(B-1)/√2) + 10.79 = 6.02·B + 1.76 dB
```

So `6.02B + 1.76` is not a separate law — it is the same law evaluated for a
full-scale sine. Its hidden assumption is `σ/LSB = 2^(B-1)/√2` (5.7 LSB of RMS
swing at 4 bits). Nothing in our datapath guarantees that.

**Gaussian / arbitrary input.** Same formula, but `σ/LSB` is whatever the data
gives. Our per-plane partials are binomial counts with `σ ≈ 3.6` counts in
`mbl = 2P - A_j`; with `LSB = 2` counts that is `σ/LSB ≈ 1.8`, i.e. **~2 bits of
usable resolution**, not 4. Plugging into the law: `20·log10(1.8) + 10.79 ≈ 15 dB`.

**Bit-plane MAC with independent per-plane noise.** The estimate is

```
M̂AC = ( LSB · Σ_{j,b} s_b·2^(j+b)·q_{j,b}  −  Σ_j 2^j A_j ) / 2 ,   s_b = ±1
```

so with independent rounding errors `ε_{j,b}` of variance `1/12`:

```
Var(err) = (LSB/2)² · (1/12) · (Σ_j 4^j) · (Σ_b 4^b)
```

The MSB plane contributes `4^(B-1)/Σ_b 4^b ≈ 75 %` of that sum at every B, so the
**MSB's quantisation noise dominates** and adding planes does not improve the
SNR: the signal power grows as `4^B` and the noise power grows as `4^B` too.

This is the user's model, and it is correct — see §4 for the numerical proof.

## 3. Why this architecture deviates: coherent rounding

The switch-matrix column sums to

```
mbl_{j,b} = 2·P_{j,b} - A_j            (A_j = number of lanes with activation bit j set)
```

`A_j` is **shared by every weight plane of a given activation bit**, so the
parity of `mbl_{j,b}` is the same for all `b`. With an LSB of exactly 2 counts
(`fs = 2^numAdcBits`, `s = 0`) the rounding error is a deterministic function of
that shared parity:

```
mbl even -> ε = 0        mbl odd -> ε = +1/2   (for every plane, same sign)
```

The per-plane errors are therefore **perfectly correlated**, not independent, and
the shift-add collapses them coherently:

```
Σ_b s_b·2^b·ε_b  =  ε · Σ_b s_b·2^b  =  ε · (-1)      (signed B-bit planes)
```

Instead of adding in power (`Σ_b 4^b`, i.e. the MSB-dominated sum), the plane
errors cancel down to a *single* term, independent of B. The residual error is
set by the parity pattern *across activation bits j*, not by the plane weights:

```
Var(err) ≈ (LSB/2)² · (Σ_j 4^j) · Var(ε_j)
```

Consequences:

* the absolute error floor is **B-independent** (measured: 37, 37, 55 counts for
  B = 2, 4, 8);
* the signal still grows by ~6 dB per plane (530 → 1882 → 30679 counts);
* hence the SNR **improves** with B (23 → 34 → 55 dB).

That is the whole reconciliation. It is not extra signal-to-noise from the extra
planes; it is a *fixed* error floor measured against a growing signal, made
possible by the coherent cancellation of the plane errors.

It is also fragile: break the parity alignment and the behaviour reverts to the
independent model. Two ways to break it, both measured below: use an `fs` that is
not a power of two (so `LSB` is fractional), or dither the quantiser.

## 4. Numerical confirmation

`an_noise_model.py` (results reproduced here) computes, for the same windows:

* `SNR` — the real model with the parity-aligned integer LSB (`fs = 16`);
* `SNR_dith` — stochastic rounding (`round(mbl/LSB + U)`, `U ~ U(-1/2, 1/2)`),
  which destroys the parity correlation and leaves independent errors;
* `pred_indep` — the closed form from §2 (`(LSB/2)²/12 · Σ_j4^j · Σ_b4^b`);
* `MSB share` — the top plane's fraction of the total error variance.

| B | fs | LSB | σ(MAC) | σ(err) | SNR | SNR_dith | pred_indep | MSB share |
|---|---|---|---|---|---|---|---|---|
| 2 | 16 | 2.00 | 530 | 37 | **23.08** | 13.60 | 14.90 | 80.0 % |
| 2 | 17 | 2.12 | 530 | 87 | 15.70 | 11.99 | 14.37 | 80.3 % |
| 4 | 16 | 2.00 | 1882 | 37 | **34.08** | 12.23 | 13.59 | 75.3 % |
| 4 | 17 | 2.12 | 1882 | 346 | 14.71 | 10.71 | 13.07 | 75.6 % |
| 8 | 16 | 2.00 | 30679 | 55 | **54.89** | 12.39 | 13.74 | 75.0 % |
| 8 | 17 | 2.12 | 30679 | 5566 | 14.83 | 10.94 | 13.21 | 75.3 % |

Reading it:

* **Dithered: 12.2–13.6 dB at every B.** The independent-noise model is right,
  and the answer is B-independent, as expected.
* **`fs = 17` (fractional LSB): 14.7–15.7 dB**, within ~1.5 dB of the closed
  form. The parity alignment is broken and the architecture behaves generically.
* **`fs = 16` (LSB = exactly 2): 23 / 34 / 55 dB.** The error floor is frozen
  while the signal grows.
* **MSB share is 75–80 % everywhere**, in both regimes. The dominant term is
  always the top plane's quantiser; what changes is whether the plane errors add
  in power (independent) or cancel coherently (parity-aligned).

## 5. So what should B = 2 have been?

"About 13 dB" is the correct expectation **for independent per-plane errors**:
the dithered run gives 13.6 dB and the closed form 14.9 dB. The 23.1 dB measured
at `fs = 16` comes entirely from the coherent-cancellation effect (a factor
`Σ_b s_b2^b = -1` instead of `Σ_b 4^b` in the noise power). At B = 2 the signal
is small (σ = 530) while the error floor (37) is the same as at B = 8, so the
apparent SNR sits between the independent value (13 dB) and the B = 4/8 values.

There is no contradiction, but there is a design lesson: the good numbers depend
on `LSB` being an exact integer so that the parity structure is shared. Any
mismatch — an odd full scale, a non-integer bias, mismatch between columns,
temperature/offset variation — degrades the converter back to ~13–15 dB. Treat
`fs = 2^numAdcBits · 2^s` (integer LSB) as a *design constraint* of the bipolar
ladder, not an accident, and keep the ~13–15 dB figure as the robust worst case
for a 4-comparator converter on this layer.

## 6. Caveats

* These are model-level numbers for one layer (seed 0). The output distribution
  is not a sine, which is why `6.02B + 1.76` does not apply directly; it would
  require `σ/LSB ≈ 5.7`, while this layer gives `σ/LSB ≈ 1.8`.
* The affine ("calibrated") SNR removes a per-channel gain/offset; it is within
  0.3 dB of the raw SNR in the aligned case, so the effect above is not a
  calibration artefact.
* Clipping is included in the error (the `clip` column of the ablation test), so
  a candidate that buys resolution by saturating does not win on SNR.
* The RTL cannot yet verify any of this: the switch matrix is blanked during
  `clk && mac_en_i` (`rtl/qr_acc_wrapper.sv:51-103`), so `tree_sum` is zero
  (`FINDINGS_multibit_prescale.md` §1).

## 7. Reproduce

```
docker run --rm -v "${PWD}:/workspaces/QrAccelerator" \
  -v "<this repo>/../tmp:/work" -w /workspaces/QrAccelerator \
  -e PYTHONPATH=/workspaces/QrAccelerator qraccelerator-qracc:latest \
  bash -c "conda run -n ic_dec python /work/an_noise_model.py"
```

`an_noise_model.py` lives beside this note in the working tree it was produced
in; the ablation test (`tests/test_marp_multibit_adc_ablation.py`) covers the
same model without the dither column.
