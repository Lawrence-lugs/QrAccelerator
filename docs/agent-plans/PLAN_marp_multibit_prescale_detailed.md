# PLAN (DETAILED) — Pre-scaling MAC golden comparison test (multibit weights)

## Goal

Compare the RTL's pre-shift MAC output (raw accumulator before `<< adc_ref_range_shifts` in `rtl/seq_acc.sv:227`) against intermediate arrays from a numpy-simulated 8b x 8b ONNX QLinearConv golden model.

The golden model computes the **entire 8b x 8b ONNX QLinearConv computation**; for the test we take the intermediate pre-scaling MAC arrays from that simulation and compare them against the RTL's pre-shift accumulator values. This avoids the pipeline-stage mismatch that made `test_marp_multibit_prestack.py` (comparing pre-shift accumulator to ONNX final post-scaler output via scale fitting) produce negative SNR (-0.3 dB for B=2/4).

---

## Confirmed design decisions

All five open questions were resolved as follows:

| # | Question | Decision | Detail |
|---|----------|----------|--------|
| 1 | Golden output semantics | **(B) ONNX-equivalent with zero-point folding** | `golden = toeplitz @ w_B − x_zp · sum(kernel per output channel)`. Matches ONNX QLinearConv pre-output-scale/zp exactly. |
| 2 | `adc_bits` parameter | **Take `adc_bits` as a parameter now** | Default/target = 4 bits, the actual RTL reference target. Code comment on that line marks 4 as the RTL reference. |
| 3 | Weight layout | **Take `mnode.matrix`, reorder internally** | Function accepts raw mapped weights; performs `transpose(0,3,2,1).reshape(O,-1).T` internally (confirmed this order makes `toeplitz @ w == conv`). |
| 4 | Function location | **`tests/utils.py`** | Test-side infrastructure, not core library code. |
| 5 | Scope | **Generalize to any QLinearConv node** | Golden function works on any conv node; the test targets `Conv_quant` specifically (`/features/features.0/features.0.0/Conv_quant`). |

### Approach selected

**Approach B (ONNX-equivalent pre-scaling MAC with zero-point folding)** — most faithful to "one-to-one with ONNX".

Approach A (pure `toeplitz @ w_B`) was rejected because it ignores input zero-point folding and will not match ONNX QLinearConv semantics. Approach C (RTL-aware golden with leaky integrator + configurable ADC) was deferred — reconnect to RTL only after the golden model is solid at ADC bits=4.

---

## Background: why the old exact-match premise is wrong

The RTL `seq_acc.sv` is a **leaky integrator** (`acc=(acc>>1)+(tree_sum<<7)` per cycle) with a **hardcoded 4-bit ADC saturating to [-8, 7]**. A direct `toeplitz @ w_B` golden model can never exactly match a pre-shift accumulator that leaks and saturates each cycle. Therefore:

1. Build the golden model first at **ADC bits=4** (RTL reference target) with `adc_bits` parameterized.
2. Verify the golden model is one-to-one with ONNX pre-scaling MAC output.
3. Only after the golden model is solid, reconnect it to the RTL test (compare golden vs RTL pre-shift `accumulator[i]` parsed from `[DBG seq_acc] pre_shift` log lines).

## Golden model specification

### Location

`tests/utils.py` — new public function (name TBD, e.g. `qlinearconv_pre_scale_mac`).

### Signature

```python
def qlinearconv_pre_scale_mac(
    mapped_node,        # core.NxModelMapping node for the conv target
    input_tensor,       # uint8 NCHW numpy array, same as RTL testbench uses
    adc_bits: int = 4,  # 4 = RTL reference target
) -> np.ndarray  # pre-scaling MAC values, shape (num_output_channels,)
```

### Internal algorithm

1. **Extract weights** from `mapped_node.matrix` (mapped weight matrix).
2. **Reorder weights** to toeplitz order: `weights_toeplitz = kernel.transpose(0,3,2,1).reshape(O,-1).T`.
3. **Get bit planes**: `planes = quant.weight_bit_planes(weights_int8, B, signed=True)` → shape `(8, *wshape)`.
4. **Build activation toeplitz matrix**: `toeplitz = compute.toeplitzize_input(ifmap, ksize, strides, channel_minor=True)`.
   - Confirmed `zero_point` handling matches RTL padding value `mapped_node.x_zp` (to be verified during implementation).
5. **Per-plane dot products**: `per_plane_dot[b] = toeplitz @ planes[b].flatten()` — one dot per plane.
6. **Combine via shift-add**:
   - B=1 (binary): `golden_pre = toeplitz @ matrix.T` (raw int32 dot products).
   - B>1 (multibit): `golden_pre = sum(per_plane_dot[b] << b for b in range(B-1)) − per_plane_dot[B-1] << (B-1)` (MSB plane negated via `twos_to_bipolar`).
7. **Zero-point folding**: subtract `x_zp · sum(kernel, axis=(1,2,3))` per output channel so result matches ONNX QLinearConv pre-output-scale/zp.
8. **ADC quantization** (optional, controlled by `adc_bits`): at `adc_bits=4`, saturate to [-8, 7] per the RTL's 4-bit ADC. At `adc_bits=32` (or large), no saturation — exact integer match.

This mirrors `seq_acc.sv`: per-plane MACs gated by `b < weight_bits_cfg`, `shift_add_tree` combines planes with `<< b`, MSB plane sign-corrected by `twos_to_bipolar`.

### Reused functions (no new library code)

- `compute.toeplitzize_input` — `qracc_marp/compile/compute.py:16`
- `quant.weight_bit_planes` — `qracc_marp/quantization/quant.py:339`
- `quant.quantize_int8_to_bits` — `qracc_marp/quantization/quant.py:324`
- `quant.twos_to_bipolar` — `qracc_marp/quantization/quant.py` (for MSB plane sign correction)

---

## Test file specification

### File: `tests/test_marp_multibit_prescale.py` (create / rewrite)

- **Marker**: `needs_verilator`, parametrized `weight_bits = [2, 4, 8]`.
- **Runs Verilator sim** with `QRACC_DEBUG=1` (`+define+DEBUG`) and `+cap_file` runtime plusarg.
- **Parses pre-shift `accumulator[i]`** from `[DBG seq_acc] pre_shift` log lines.
  - Parser regex: group(4) = accumulator value, group(6) = mac_data_o hex (already fixed in current test file).
- **Computes numpy golden** from the same random `input_tensor` + mapped node weights using `qlinearconv_pre_scale_mac`.
- **Success metric**: exact (or near-exact, allowing for trivial zero-padding) match between golden pre-shift values and RTL pre-shift accumulator values.
- **PNG scatter** via `save_scatter_fig` → `images/png/multibit_prescale_B{n}.png`, gated by `--figures`.

### QRACC_DEBUG import-time ordering (critical)

`tests/utils.py` builds `sim_args['verilator']` at **module import time**. At lines 68-69 it appends `+define+DEBUG` to the verilator sim args only if `os.environ.get('QRACC_DEBUG') == '1'` **at import time**.

This means:
- `QRACC_DEBUG=1` must be set in the environment **before** importing `tests.utils` (or `diag_utils`), OR
- if set after import, you must **also** explicitly append `+define+DEBUG` to `sim_args['verilator']`.

Setting `os.environ['QRACC_DEBUG'] = '1'` inline **after** importing utils is **too late** — the define will not be present during compilation, debug dump blocks are not compiled in, and no pre-shift debug values are captured.

### Test command (inside Docker, per AGENTS.md)

```
docker compose run --rm qracc bash -c "conda run -n ic_dec python -m pytest tests/test_marp_multibit_prescale.py -v --figures --simulator verilator"
```

The `qraccelerator-qracc:latest` image already exists locally.

---

## Files to create / modify

| File | Action | Rationale |
|------|--------|-----------|
| `tests/utils.py` | **Modify** — add `qlinearconv_pre_scale_mac` golden function | Test-side infrastructure, location per decision #4 |
| `tests/test_marp_multibit_prescale.py` | **Create / rewrite** — new pytest test using the golden function | Per plan; currently exists in stale state (parser fixed, DEBUG append applied, but golden uses outdated pure `toeplitz@w_B`) |
| `rtl/seq_acc.sv` | No change | Already has pre-shift debug dump (committed in `330d0fa`) |
| `rtl/ts_qracc.sv` | No change | Already has mbl_value debug dump (committed in `330d0fa`) |
| `tests/conftest.py` | No change | Already has `--figures` flag (line 57) and `needs_verilator` skip logic (line 124) |
| `PLAN_marp_multibit_prescale.md` | No change | Original plan; this detailed plan supersedes it for implementation guidance |

---

## Known issues / risks to track during implementation

1. **B=2 Verilator run captured 512 pre_shift events but ALL ZERO** — seq_acc not receiving activations (`dbg_nz==0`, `mac_data_i` all zero). Likely `qracc_controller.sv` `act_wr_ptr` doesn't increment during ifmap load (lines 544-566). This is an RTL-side issue; the golden model work is independent of it.
2. **Padding/zero-point handling** — toeplitzize uses `zero_point`; confirm it matches RTL's padding value `mapped_node.x_zp`.
3. **Mapped weight extraction** — confirm `core.NxModelMapping` exposes `mapped_bin.weights` for the target node `/features/features.0/features.0.0/Conv_quant`.
4. **Exact vs approximate match** — bit-plane decomposition is exact integer math; confirm no rounding in the numpy path that would prevent exact ONNX match.

---

## Implementation order

1. Write `qlinearconv_pre_scale_mac` in `tests/utils.py` (with `adc_bits` param, default 4).
2. Write/rewrite `tests/test_marp_multibit_prescale.py` using the golden function.
3. Run the test inside Docker (Verilator, `QRACC_DEBUG=1`, `--figures`).
4. Investigate the B=2 all-zero RTL activations issue separately (RTL side, `qracc_controller.sv`).
5. Once golden model is solid at ADC bits=4, finalize exact-match vs near-exact-match success criteria.
