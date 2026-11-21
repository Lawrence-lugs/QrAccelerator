# PLAN — end-to-end RTL fixes against the ONNX golden

Status: **active.** E1, E2.1, and the first E3 chain are complete; E4 full-model
multibit and E5 CI wiring remain. The node-level post-scaler is certified.

## 0. Ground rules

1. The ONNX output is the reference. `qlinearconv_onnx_reference` runs the
   same node on the **same input** with the hardware's B-bit weights.
2. `qlinearconv_post_scale_mac` is the Python model of the RTL contract. It
   must match ONNX before it is allowed to judge RTL.
3. Never tune the golden to match a broken RTL result. A change is valid only
   if the RTL moves toward ONNX.
4. Every fix gets a test that fails before and passes after.

Current truth table:

| case | status |
|---|---|
| Python post-scale model vs ONNX, B=2/4/8 | **exact, RMSE 0** |
| RTL conv node, B=2 | **62.690 dB** |
| RTL conv node, B=4 | **38.491 dB** |
| RTL conv node, B=8 | **36.086 dB** |
| Binary single-node matrix, 8 nodes | **8/8 before ADC change**; node 0 rerun at 21.310 dB, others need rerun |
| ADC unit sweep | **s=0..8** after extending `tb_ts_qracc` |
| Depthwise PE unit tests | **3/3 exact** |
| B=1 binary post-scale golden | **exact, RMSE 0** |
| Depthwise post-scale golden | **exact, RMSE 0** |
| Final matmul post-scale golden | **exact, max diff <= 1** |
| Binary chain conv -> depthwise | **stage0 21.3 dB, stage1 34.9 dB** |
| Full multi-node multibit | **not yet certified** |
| ADC full scale = `numRows`, `s<=8` | **implemented**; s=4 chosen for the target conv (LSB 2) |

## 1. Phase E1 — complete the golden matrix — DONE

`qlinearconv_post_scale_mac` and `qlinearconv_onnx_reference` now cover:

* **B=2/4/8 conv**: exact (RMSE 0)
* **B=1 binary**: exact (0/1 weights, no 2x, raw scale)
* **depthwise**: exact (raw WSAcc kernel, no 2x)
* **final QLinearMatMul**: exact to the int8 rounding boundary (max diff <= 1)

The tests are `test_python_postscale_model_matches_onnx`,
`test_python_postscale_binary_model_matches_onnx`,
`test_python_postscale_depthwise_binary_matches_onnx`, and
`test_python_postscale_matmul_binary_matches_onnx`.

Historical E1 description:

* **B=1**: `qlinearconv_post_scale_mac` needs a binary branch:
  no `2*MAC`, no `2**(8-B)`, `binary_cfg=1`, scaler scale unchanged.
* **depthwise**: model the WSAcc output/scaler; `rtl_publishes_2x` is false.
* **matmul / final nodes**: use `qlinearconv_onnx_reference` where possible;
  for QLinearMatMul use the same B-weight + w_scale rule.
* **adc_mode**: keep `"none"` for exact model checks and `"per_plane"` for
  the RTL comparison; print `adc_config` (`s`, `fs_counts`) in every test.

Acceptance: a pure Python test matrix over `{B=1,2,4,8} × {conv, depthwise,
matmul}` matches ONNX before any simulator run.

## 2. Phase E2 — node-level RTL matrix

For each node type and B, run the existing node harness with the same-input
ONNX reference. This is where the remaining RTL fixes become visible.

Expected fixes, in order of likelihood:

1. **ADC full scale is now fixed at the bank maximum — IMPLEMENTED.**
   `adcFullScale = numRows` (256 for the current core), the realistic
   "fully loaded bank" half-span.  The chooser no longer searches
   `fs_counts`; `QrAccNodeCode.config()` passes
   `fs_counts=imc_core_size[0]` and `s_max=8`.  `seq_acc` defaults to
   `inputElements`; `ts_qracc` / `ts_qracc_multibank` default to `numRows`.
   The old B=1 `fs=23` mismatch is gone.
   `s` is a natural number; `s<=8` is the practical limit because the LSB
   approaches the ~16 mVrms comparator noise floor (the 4-bit field allows
   more).  Per-ADC data will later become loaded scaler-like data.
   Because `seq_acc` publishes `(2*MAC) << s`, the compiler scaler now divides
   the scale by `2**s` and pre-shifts the bias by `2**s`.
   Regression: `test_adc_config_uses_bank_full_scale` asserts
   `fs_counts == 256`, `0 <= s <= 8`, and the corresponding LSB for B=1/2/4/8.
2. **B=1 compiler branch.** `rtl_publishes_2x` is false and `binary_cfg=1`;
   verify the scaler path does not apply the multibit 2×/`2**(8-B)`.
3. **Depthwise.** No 2×; verify the WSAcc bias/zero-point and output packing
   with the same golden.
4. **Output packing.** `mm_output_aligner` + PISO + bus read order for a
   non-zero `mapped_matrix_offset_x`; check channels, not just aggregate SNR.
5. **Padding / zero point.** `padding_value = x_zp` and `bias_B` re-fold must
   agree for every node, including non-zero `x_zp`.

Acceptance: node-level RTL SNR meets a per-type threshold (conv ≥ 30 dB for
B=8, ≥ 20 dB for B=2/4; depthwise/matmul thresholds set from their golden).

### Split / fan-out decision

Depthwise blocks in MobileNetV2 are fed by channel `Slice` nodes.  The chosen
implementation is **internal split**, not an external-memory materialization:

* keep the parent activation resident in ACTMEM;
* give each slice consumer a per-node `ifmap_channel_stride` (the parent
  channel count) and `ifmap_channel_offset` (the slice base channel);
* use `preserve_ifmap` to keep the parent base live while consecutive slice
  consumers run, while still advancing the output base for each consumer;
* do not write a split result through an external buffer.

This requires the controller to separate “keep input base” from “allocate a new
output base”; the current code only advances `ofmap_start_addr` when not
preserving, which would make slice consumers overwrite the parent.

Status: implemented in the compiler and controller:

* `ifmap_channel_stride` / `ifmap_channel_offset` in the CSR config;
* Slice-parent resolution in `traverse_and_compile_nx_graph`;
* parent-base preservation with independent output-slot advancement.

The first 5-node validation run did not complete cleanly: one attempt was
contaminated by an old container, and the clean attempt was interrupted by a
Docker daemon failure. The 3- and 4-node regressions remain the active gates
until the 5-node split test is re-run.

## 3. Phase E3 — chained two-node test

Feed the RTL output of node A into node B, both compiled through MARP, and
compare each stage with ONNX:

```
ONNX A -> ONNX B
RTL  A -> RTL  B
```

This catches errors that a single-node test cannot: output layout, channel
order, signedness, zero point, activation packing, and scaler state.

Acceptance: `RTL_A ≈ ONNX_A`, `RTL_B ≈ ONNX_B`, and the error does not grow
beyond the per-stage budget. This is the first true e2e gate.

Implemented:

* `test_marp_binary_chain_conv_depthwise` — node 0 conv feeds its NHWC RTL
  output back as NCHW into node 1 depthwise: stage 0 **21.278 dB**, stage 1
  **34.890 dB**.
* `test_marp_e2e_multibit_slice` — contiguous slices, B=8, real ONNX
  activations:
  * 3 nodes (conv -> depthwise -> conv): **21.825 dB**
  * 4 nodes (conv -> depthwise -> 1x1 -> 1x1): **19.559 dB**.

The 3-node test exposed two ACTMEM bugs: the internal read address lacked
`ifmap_start_addr`, and an unpadded 1x1 node inherited the previous 3x3
padding window and zeroed valid data. Both are fixed in
`rtl/control/qracc_controller.sv`; see FINDINGS §14.

## 4. Phase E4 — full model

Started. `traverse_and_compile_nx_graph` now accepts a scalar or per-node
`weight_bits`, `real_activations=True`, global graph-node indexing and forced
final readout. The 3-node conv/depthwise/conv chain passes at 21.825 dB and
the 4-node slice at 19.559 dB (B=8).

Still to do:

* Run the whole graph (or a larger subgraph) through that path.
* Carry `adc_config`, `scale`, and `bias_B` per node (already per-node in
  `QrAccNodeCode`, but not yet exercised over many layers).
* Compare final logits / top-1 against ONNX on the same input.
* Only then run the full MBV2 accuracy check.

Expected RTL fixes if E3 passes but E4 fails:

* per-layer `weight_bits` selection and weight reduction in the compiler;
* `adc_ref_range_shifts` / `adcFullScale` per layer;
* output-zero-point and int8 saturation at the model boundary;
* matmul/final-layer path (currently the binary model only).

Acceptance: final output SNR and top-1 delta stated explicitly; no regression
in `test_seq_acc`, `test_rtl_multibit_verify`, prestack, postscale, or WSAcc.

## 5. Phase E5 — regression lock

Add these to the standard verilator gate:

* `test_python_postscale_model_matches_onnx` (no simulator, exact)
* `test_marp_multibit_postscale` B=2/4/8
* `test_marp_multibit_node_int8` B=2/4/8 (same-input ONNX)
* the new chained test
* `test_qracc_with_onnx_single_node` 8/8
* `test_wsacc_dw*`

## 6. What not to do

* Do not change `qlinearconv_onnx_reference` to make RTL pass.
* Do not hide the 2× in an unstated test scale; it belongs to the compiler
  (`scale * 2**(8-B) / 2`, `bias * 2`).
* Do not reuse the old fixed-image `.npy` files.
* Do not certify e2e from the prestack MAC test; it is pre-scaler only.

## 7. Immediate next action

E1 and the first E3 chain are complete.

1. Extend the chain beyond node 1 (node 0 -> 1 -> 2, then a strided layer) to
   exercise output packing and shape changes.
2. Add B=2/4 multibit chain stages once the per-layer B and ADC config are
   carried through `traverse_and_compile_nx_graph`.
3. Keep `adcFullScale=numRows`, `s<=8` until the loaded per-ADC schema
   replaces the compile-time reference setting.

## 8. Internal channel-slice status (2026-11-20)

Decision: a Slice consumer reads the parent activation in ACTMEM with a
channel stride/offset; do not materialize the slice in external memory.

Implemented and committed in `9220792`:

* `ifmap_channel_stride` / `ifmap_channel_offset` in `qracc_config_t`,
  CSR weight word, compiler, and controller `rel_addr`.
* `traverse` resolves a channel Slice to its parent, sets stride to the
  parent output-channel count, offset to the slice start, and keeps the
  parent live for the remaining slices.
* 5-node compile trace (`conv32 -> dw32 -> 1x1/16 -> 1x1/96 -> dw-slice0`)
  is correct: split0 gets `in=32 out=32 stride=96 off=0`, parent base 23632.

Validation is **not complete**:

* no-debug 5-node result was **-2.291 dB** before the latest controller
  experiments;
* ACTMEM debug shows node0-3 run and the split0 config is loaded with the
  correct base/stride, but the split never advances past `S_COMPUTE_DIGITAL`
  (`0 -> 4`, no `4 -> 0`, no ACTMEM reads from the split);
* experiments adding `result_start_addr`, a level `~int_write_queue_valid`
  exit condition, and a separate `wsacc_ready` did not change the 5-node
  result; the latest debug run stalls in the digital state with no reads.

Suspects, in order:

1. `feature_loader_valid_out_qq` / `window_data_valid_q` is stale after the
   preceding analog node, so the split enters digital but never accepts a
   window (no ACTMEM read).
2. `last_window` / `read_set` never advance because the feature loader never
   produces a window (same stall).
3. The split's `output_fmap`/padding state is correct (16x16, pad1) but the
   controller is stuck before the first read, so padding is not the cause.

Next isolation step: preload node3's 96-channel output into ACTMEM and run a
single split node, so the split can be debugged in seconds instead of
replaying 20+ minutes of prefix nodes. The expected split output is the
original ONNX depthwise output channels 0:32 (depthwise channels commute with
the Slice). Once that passes, re-run the 5-node chain and then all three
slices.

Until this is fixed, `test_marp_e2e_multibit_slice` stays parametrized
`[3, 4]`; do not claim internal-split certification.

## 9. Cold-start vs chained depthwise (2026-11-20)

A preloaded cold-start split test was built to separate split data correctness
from controller state:

* input: node3's 96-channel ONNX output, channel slice 0:32;
* expected: original ONNX depthwise output channels 0:32;
* compile: single `QrAccNodeCode` for `split_4_qconv_0` with
  `include_ifmap_writes=True`, weights, scaler, bias, compute, read.

Result: **34.083 dB** (RMSE 0.52). The split depthwise datapath, weight slice,
output layout and standalone control sequence are therefore correct.

A second test preloaded the full 96-channel parent with a temporary
`num_input_channels=96` config and then ran the same split with stride 96. It
gave **-3.507 dB**, i.e. the same class of failure as the chained run. This
points at the **parent 96-channel ACTMEM layout / stride-96 read**, not at the
depthwise PE.

Cold vs chained differences to isolate next:

1. cold uses `LOADACTS` for the split and compact stride 32;
2. chained uses no load for the split and stride 96 with parent base 23632;
3. warm preload with stride 96 also fails, so the split itself is fine but the
   parent layout at stride 96 is not what the split expects.

Next: dump node3's ACTMEM output words for pixel 0 and compare against
`parent_out[0, :, 0, 0]` (all 96 channels), then check whether the
`piso_write_queue`/`mm_output_aligner` output is bank-major or channel-major.
Do not change the split read until that dump is understood.

## 10. Node3 layout check (2026-11-20)

Single-node node3 (96-channel pointwise conv) cold run:

* SNR **29.464 dB**, RMSE 0.878;
* `[DBG out]` first 96 ACTMEM bytes at `ofmap_start_addr` match
  `parent_out[0, :, 0, 0]` almost exactly (0-1 LSB differences);
* therefore the 96-channel parent output **is** contiguous channel-major and
  stride 96 is the correct view.

This rules out the parent layout as the cause. The cold split also passes
(34.083 dB), so both the split and the parent are individually correct.

Remaining difference is the **control/trigger sequence**, not data layout:

* command trace includes the split config, weight load, digital trigger
  (`LOAD ... 4`) and read trigger (`LOAD ... 5`) after node3;
* the chained run still produces -2.291 dB and debug did not show a clean
  split read sequence.

Next: add a state/trigger trace around the split entry and capture
`state_q == S_COMPUTE_DIGITAL (7)`, `cfg.ifmap_channel_stride=96`,
`ifmap_start_addr=23632`, and the first four `activation_buffer_int_rd_addr`
values. Compare those against the cold split's `state_q == 7` sequence.

## 11. Read-set stride bug (2026-11-20)

Found and fixed a real internal-slice addressing bug:

```
rel_addr += read_set * internalInterfaceElements
```

assumed a compact ifmap. For a channel-slice consumer the parent pixel stride
is larger, so each 32-element read-set chunk spans
`32 / num_input_channels` parent pixels:

```
rel_addr += read_set * internalInterfaceElements
            * ifmap_channel_stride / num_input_channels
```

For the 96-channel parent and a 32-channel slice this changes the read-set
offset from 32 to 96.

Evidence:

* manual node3 -> split0 chain: **-3.951 dB before, 25.707 dB after**
  (RMSE 35.8 -> 1.23);
* cold compact split remains 34.083 dB;
* node3 single-node output remains 29.464 dB and its ACTMEM dump is
  contiguous channel-major.

The full 5-node test still reports **-2.291 dB** after the fix, unchanged from
before, so there is a second issue in the full-prefix path or in the 5-node
test's expected/readout mapping. Do not claim the 5-node chain yet. The manual
node3 -> split0 chain is the clean evidence that the read-set fix is correct.

Next: run the 5-node test with ACTMEM debug after this fix and compare its
split read addresses (expected base + 0, 96, 192 ... for pixel 0) and split
output base against the manual chain.

## 12. Preserving readout and depthwise weights (2026-11-20)

Two more fixes were required for the direct node3 -> split0 chain:

* `result_start_addr`: a preserving node keeps the parent in
  `ifmap_start_addr`; `S_READACTS` must read the saved output base. With this,
  the preserving manual chain goes from **-2.327 dB to 25.707 dB**.
* depthwise weights must be loaded even when the analog bin id is reused;
  `write_weights` is now true for every depthwise node.

The direct node3 -> split0 chain now passes **25.707 dB** in both
`preserve_ifmap=False` and `preserve_ifmap=True` modes.

The full 5-node test still reports **-2.291 dB**, exactly unchanged. Its actual
output has correlation 0.014 with the expected split output and is not close to
the parent or depthwise slice either. That is not explained by the direct
chain fixes. Next: dump the full-prefix node3 output at base 23632 and compare
it with the manual node3 output at base 4096, then check whether the split
writes/readout in the full path use base 48304.

## 13. Python input proof: 5-node reads node3 output (2026-11-20)

Definitive check of the e2e output file:

```python
a4 = 4-node hw_ofmap (1,16,16,96)
a5 = 5-node hw_ofmap (1,16,16,32)
a5 == a4.reshape(-1)[:16*16*32].reshape(1,16,16,32)   # exact, maxdiff 0
```

So the failing 5-node file is **exactly the first 32768 bytes of node3's
96-channel output**, re-read as 32 channels. It is not a wrong depthwise result;
the split's output is never read (or `result_start_addr` is still node3's base
when `S_READACTS` starts).

Additionally:

* full `traverse` split command list and manual passing split command list are
  **both 2646 lines and diff-empty**;
* so config, weights, scaler, bias, triggers and addresses are identical;
* direct node3 -> split0 passes at 25.707 dB in both preserve modes;
* the failing file is exactly the parent, so the remaining difference is
  runtime readout/trigger state, not compilation.

Current fixes retained:

* `2164003` read-set stride scaling;
* `ec3ab3f` preserving readout + chained depthwise weights + stale-output
  removal.

Next: determine whether the full-path split enters `S_COMPUTE_DIGITAL` at all,
and whether `result_start_addr` changes to the split output base before
`TRIGGER_READ_ACTIVATION`. The exact parent-file equality means the readout
base is still node3's.

## 14. 5-node slice passes (2026-11-20)

Root cause of the last failure: `traverse` marked node3 as `readout=True`
because its immediate consumer was a Slice (non-compilable), even though the
next compilable consumer (split_4_qconv_0) resolves to node3 itself through
that Slice.  The extra external readout left the readout pipeline on node3's
output; the split then ran but its output was not read.

Fix: suppress `readout` when the next compilable consumer's resolved parent is
the current node's output.

Result: `test_marp_e2e_multibit_slice[verilator-5]` **passes at 19.910 dB**
(RMSE 2.326).

Direct checks remain:

* cold compact split: 34.083 dB
* node3 single: 29.464 dB
* node3 -> split0 manual, both preserve modes: 25.707 dB
* 4-node chain: 19.559 dB
* 5-node chain: 19.910 dB

## 15. Regression status (2026-11-21)

* `test_marp_e2e_multibit_slice[verilator-3]`: **19.559 dB** (3-node)
* `test_marp_e2e_multibit_slice[verilator-4]`: **19.559 dB** (4-node)
* `test_marp_e2e_multibit_slice[verilator-5]`: **19.910 dB** (node3 -> split0)

All three pass after the spurious-readout fix (`6adc6df`).  The next gate is
`n_nodes=7`, which exercises all three 32-channel depthwise slices.

## 16. All-three-slices gate (n_nodes=7) (2026-11-21)

`test_marp_e2e_multibit_slice[verilator-7]` fails at **-2.872 dB**.

The actual output is **split0**, not split2:

```
corr(actual, ONNX depthwise channels 0:32)  = 0.995
corr(actual, channels 32:64 / 64:96)       ~ 0.04 / -0.05
```

Command trace shows all three split compute triggers, each with
`0x1004` (trigger 4 + preserve bit 12), and read triggers between them.
So the compiler emits the right sequence; the later preserve/readout path is
not advancing to split1/split2 output.

Next: trace `result_start_addr`, `ofmap_start_addr`, and `csr_set[MAIN][12]`
after each split, and the `S_READACTS` base for split1/2. The direct 5-node
case and the manual preserve chain both pass, so the remaining issue is
specific to multiple consecutive preserving splits.

## 17. Multiple preserving splits: only split0 writes (2026-11-21)

A manual three-split chain (node3 -> split0 -> split1 -> split2), with all
three using `preserve_ifmap=True` and their own readout, reproduces the
7-node failure at **-2.863 dB**.

Debug evidence:

* all three splits enter `S_COMPUTE_DIGITAL` and issue reads;
* their first read addresses differ by 32 (`-1632`, `-1600`, `-1568`), so the
  channel offsets are applied;
* only **split0** produces `[DBG actwr]` writes at base `28768`;
* split1 and split2 produce no `activation_buffer_int_wr_en` writes, so the
  final readout still selects split0.

So the failure is in the **WSAcc output-valid/write path for consecutive
preserving split nodes**, not in read addressing or the compiler command
stream.  The 5-node case has only one split and passes.

Next: trace `wsacc_output_valid` / `activation_buffer_int_wr_en` across all
three splits and check whether the WSAcc output pipeline is being held in
reset/stall after a preserving node.  Do not change read addressing.

## 18. Testbench L2 readout pointer bug (2026-11-21)

The 7-node output being "split0" was a **testbench/Python-facing bug**, not
RTL:

* `l2_mem_addr` was reset only by `nrst`;
* every `WAITREAD` appended at the current pointer;
* `export_l2()` always exports `l2_mem[0..ofmap_size-1]`, i.e. the **first**
  readout ever performed (split0);
* all three splits do write 256 outputs each (`[DBG wsacc-node] in=256 out=256
  wr=256` at 56528, 64752, 72976).

Fix: reset `l2_mem_addr = 0` at the start of each `WAITREAD`.

Also added under `ACTMEM_DEBUG`:

* a timestamped `$monitor` stream for digital state;
* per-node `wsacc-data-i-valid` / `wsacc-output-valid` / write counters.
