# CRITIQUE — unsigned multibit activation conventions (and the MSB hijinks)

Status: open cleanup item. This file is a hand-off for an agent that will
solidify input-width/sign conventions across `rtl/`, `tb/` and `tests/`.
It records why the 2026-11-18 unsigned multibit debug cycle was possible and
what must be renamed/asserted so it cannot recur.

## 1. What happened

The `test_marp_multibit_prestack` end-to-end test initially correlated with the
golden at `~0.03` even after the datapath, SRAM weights, ADC and activation
vectors had all been verified individually. The root cause was the treatment
of the **top bit of an unsigned 8-bit activation**:

* `rtl/twos_to_bipolar.sv` interpreted bit `input_bits-1` as a sign bit for
  every activation. That is right for the ternary/signed convention the base
  qracc bank was developed with, but **wrong for unsigned multibit ONNX
  activations**, where all eight bits are data.
* `seq_acc` computed `input_bits = n_input_bits_cfg + unsigned_acts` and then
  `input_trits = input_bits - 1`. For uint8 that is `9 - 1 = 8`, but `uint8`
  values with bit 7 set were still converted as if negative.
* An attempted fix widened the whole lane to 9 bits (`QRACC_INPUT_BITS=9`).
  That changed `feature_loader.elementWidth` from 8 to 9 while the host bus
  still carries byte-packed 8-bit data; the write-decode
  (`inputWidth/elementWidth`) then mis-packed the ifmap. The correlation got
  worse, not better.
* The correct fix kept the lane at 8 bits:
  * `twos_to_bipolar` got an `unsigned_acts` bypass (`p = value`, `n = 0`);
  * `seq_acc` uses `input_trits = n_input_bits_cfg` for unsigned acts
    (8 for uint8) and `n_input_bits_cfg - 1` for signed/ternary;
  * `QRACC_INPUT_BITS` stays 8.

The user's note is the canonical statement of the convention:

> “the uppermost bit is a SIGN BIT for ternary inputs X (when ternary input is
> enabled — we don't need it for multibit cases to match ONNX, really). It's
> not twos complement.”

## 2. Names that currently collide

| name | where | current meaning | problem |
|---|---|---|---|
| `xBits` | `tb/seq_acc`, `tb/qracc`, tests | lane width including sign/ternary bit for signed, raw width for unsigned | reads like “number of data bits”, but a signed 8-bit lane has only 7 trits |
| `xTrits` | tests / `tb/seq_acc` local | `xBits` if unsigned else `xBits-1` | duplicates `input_trits` with a different name |
| `trits` | prose/comments | usually activation bit-planes, sometimes ternary digits | overloaded: bit-plane count vs ternary radix |
| `n_input_bits_cfg` | CSR / `qracc_config_t` | programmed input precision (8 for uint8/int8) | does not say whether the top bit is sign or data |
| `unsigned_acts` | CSR / `qracc_config_t` | 1 = unsigned activation | says “unsigned”, but the datapath also uses it to choose the trit count |
| `input_bits` | `seq_acc` | lane width used by `twos_to_bipolar` for sign detection | for unsigned it is `n+1` in the formula, but the lane is not widened; misleading |
| `input_trits` | `seq_acc` | number of PISO bit-planes processed | correct concept, but derived inconsistently from `input_bits` |
| `qrAccMaxInputBits` | `qracc_pkg` | 9 (max lane width) | looks like “max data bits”, but it is a lane/sign capacity |
| `twos_to_bipolar` | RTL module | converts signed/ternary two's-complement-ish input to p/n magnitudes | name implies two's complement only; it also carries the unsigned bypass now |
| `weight_bits` / `weight_signed` | CSR / compile | weight plane count / MSB-plane sign | orthogonal to activation sign, but easy to conflate |

`xBits`, `xTrits`, `input_bits`, `input_trits` and `n_input_bits_cfg` are four
different spellings for two concepts (lane width and processed bit-planes).
`unsigned_acts` silently changes the relationship between them.

## 3. Proposed canonical convention

Use two explicit concepts everywhere:

1. **`act_lane_bits`** — physical lane width in the feature loader/PISO
   (8 for both `uint8` and `int8` ONNX tensors; 9 only if a future format
   genuinely carries a separate sign/mode bit).
2. **`act_data_bits`** — number of activation bit-planes the MAC processes:
   * unsigned multibit: `act_data_bits = act_lane_bits` (all bits are data);
   * signed/ternary: `act_data_bits = act_lane_bits - 1` (top bit is sign/mode).

Then require an explicit mode enum instead of a boolean that changes two
things at once:

```systemverilog
typedef enum logic [1:0] {
    ACT_UNSIGNED = 2'd0,  // all lane bits are data; p = value, n = 0
    ACT_SIGNED   = 2'd1,  // top bit is sign; magnitude below; p/n conversion
    ACT_TERNARY  = 2'd2   // ternary sign/mode bit; same p/n conversion
} act_format_t;
```

`unsigned_acts` may stay as the CSR bit for compatibility, but RTL should decode
it once into `act_format_t` (or at least into `act_data_bits` and a
`sign_bit_en` flag) rather than recomputing `input_bits` in several places.

`twos_to_bipolar` should be renamed (e.g. `act_to_bipolar`) and take an explicit
`sign_bit_en`/`act_format` input. The unsigned bypass must be a first-class
case, not an afterthought.

## 4. Invariants to assert in tests

For every activation word `x` and data-bit count `T`:

```
unsigned:  A_j = popcount((x >> j) & 1)          for j = 0..T-1
           sum_j 2**j A_j == sum(x)               (bias identity)
signed:    A_j = popcount(p_j) - popcount(n_j)    (p/n from the sign/magnitude
                                                   conversion)
           sum_j 2**j A_j == sum(x)
```

The bias identity is the cleanest single check: it caught the missing bit-7
trit and must be part of the unit TB for every `(lane_bits, format)` pair.

Also assert:

* `act_data_bits == lane_bits` for unsigned;
* `act_data_bits == lane_bits - 1` for signed/ternary;
* the feature-loader element width equals the activation lane width used by
  the host packing (do not widen only one side);
* `sum_j 2**j A_j` for T=8 includes `A_7 * 128` (the exact term that was lost).

## 5. Migration checklist for the cleanup agent

- [ ] Rename `xBits`/`xTrits` in `tb/seq_acc`, `tb/qracc` and tests to
      `act_lane_bits`/`act_data_bits` (or keep aliases with a deprecation
      comment).
- [ ] Replace `input_bits`/`input_trits` derivation in `rtl/seq_acc.sv` with a
      single `act_format` decode; add assertions for unsigned/signed.
- [ ] Rename `twos_to_bipolar` and take an explicit format input; document that
      it is sign/magnitude, not plain two's complement.
- [ ] Add a compile-time assertion or elaboration check that
      `act_lane_bits == feature_loader.elementWidth` and that the host bus
      width is an integer multiple of the lane width.
- [ ] Add the bias identity to `tests/test_rtl_multibit_verify.py` for
      unsigned/signed, T=7/8, B=2/4/8.
- [ ] Remove `qrAccMaxInputBits = 9` ambiguity: document it as a
      lane/sign-capacity maximum, or replace with `act_lane_bits` + explicit
      format.
- [ ] Update `AGENTS.md`/`FINDINGS` references to the old names.

## 6. What not to do

* Do **not** fix unsigned MSB handling by widening `QRACC_INPUT_BITS` to 9:
  the host/feature-loader packing is byte-based, and widening one side
  mis-packs every subsequent element.
* Do **not** treat `unsigned_acts=1` as “two's complement with the sign bit
  ignored”. It means “all bits are data”; the sign bit exists only in the
  signed/ternary mode.
* Do **not** infer the trit count from `input_bits` alone; the format is part
  of the contract.

## 7. References

* `rtl/seq_acc.sv` — `input_bits_raw`, `input_bits`, `input_trits`,
  `act_popcount_q`, `bipolar_bias_sub` instantiation.
* `rtl/twos_to_bipolar.sv` — `unsigned_acts` bypass.
* `tb/seq_acc/tb_seq_acc.sv` — `xBits`, `unsignedActs`, `numAdcBits`.
* `tests/test_rtl_multibit_verify.py` — `unsigned_acts` reference and streaming
  cases.
* `FINDINGS_multibit_prescale.md` §11.4 — the incident and fix.
* `tests/test_marp_multibit_prestack.py` — end-to-end unsigned uint8 path.
