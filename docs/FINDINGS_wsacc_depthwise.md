# FINDINGS — WSAcc depthwise path

Date: 2026-11-18
Status: **RESOLVED.** PE arithmetic is bit-exact; the full-node depthwise
failures were caused by the shared output scaler treating Q0.16 scale as
signed. After that fix, nodes 1 and 4 pass at 47.4 dB.

This is a separate datapath from the analog multibit bank. Do not use the
multibit MAC results to claim WSAcc is end-to-end correct; use the node tests
and the unit tests below.

## 1. What WSAcc is

`rtl/wsacc/wsacc_pe_cluster.sv` / `rtl/wsacc/wsacc_pe.sv` implement the
**digital** depthwise convolution path: signed int8 weights times unsigned
activations, accumulated in each PE, then fed to the same `output_scaler_set`
as the analog MAC path. It does not use `ts_qracc`, `seq_acc`, the flash ADC,
or the bipolar switch matrix.

In `rtl/qr_acc_top.sv` the scaler input is selected by
`qracc_ctrl.wsacc_active`:

```
oscaler_input = wsacc_active ? wsacc_data_o : qracc_mac_output;
```

## 2. Unit verification (passes)

`tests/test_wsacc_dw.py` and `tests/test_wsacc_dw32.py` drive the PE cluster
directly and compare every PE output with the numpy depthwise sum.

```
docker run --rm -v "$(pwd):/workspace" -w /workspace qraccelerator-qracc \
  bash -c "conda run -n ic_dec python -m pytest tests/test_wsacc_dw.py tests/test_wsacc_dw32.py -q"
```

Result: **3 passed** (exact `data_o == golden`, including a real 32-channel
3x3 layer).

## 3. Full-node failure (open)

In `tests/test_marp_rtl.py::test_qracc_with_onnx_single_node`, the depthwise
nodes are indices **1** and **4** (`kernel=(32,1,3,3)`). Both fail:

| node | depthwise | SNR before | SNR after scaler fix |
|---|---|---|---|
| 1 | yes | -2.383 dB | **47.409 dB** |
| 4 | yes | -3.068 dB | **47.409 dB** |

The non-depthwise nodes failed too (0, 2, 3, 308, 309), so the failure was not
unique to WSAcc. It was the shared post-scaler, not the WSAcc PE.

### Root cause

`rtl/output_scaler/output_scaler_set.sv` declared `output_scale` as signed
Q0.16.  Every multiplier >= 0.5 therefore appeared negative (bit 15 set), and
the scaler flipped the sign of the output.  The analog and WSAcc paths share
this scaler, so both failed with a bias-only-looking output.  Fixed by
declaring the scale unsigned and zero-extending it in the multiplier.

The single-node test currently uses `weight_bits=1`; the depthwise branch of
`QrAccNodeCode` writes the physical kernel and issues
`TRIGGER_COMPUTE_DIGITAL`, so this is the WSAcc path.

## 4. What is ruled out

* **PE arithmetic / weight packing** — bit-exact in
  `test_wsacc_dw32.py`, including the `physical_kernel.transpose(1,2,3,0)`
  KHWC packing used by `QrAccNodeCode._get_weight_data`.
* **The analog ADC / `seq_acc` / bipolar bias** — not in the WSAcc path.

## 5. Open hypotheses, in order

1. **Output scaler / bias** — `output_scaler` is shared with the analog path;
   the WSAcc output is wider than the 4-bit ADC path and may need a different
   `output_bias`/`output_scale` calibration or a different `cfg_output_bits`.
2. **Activation layout / padding** — the depthwise kernel uses a different
   receptive-field order from the pointwise toeplitz; check the WSAcc input
   window order against `QrAccNodeCode` and the padder.
3. **Output alignment / readout** — `mm_output_aligner`, `piso_write_queue`,
   and the bus read order may be wrong for the WSAcc channel-parallel output.
4. **Reference layout** — the depthwise ONNX output transpose and the
   `result_shape` used by the test may not match the hardware's NHWC order.

The fastest discriminator is to dump `wsacc_data_o`, `oscaler_input`, and
`output_scaler_output` for one known depthwise window and compare each against
the numpy PE sum and the ONNX reference, independent of the bus readout.

## 6. Repro

```
docker run --rm -v "$(pwd):/workspace" -w /workspace qraccelerator-qracc \
  bash -c "conda run -n ic_dec python -m pytest \
  'tests/test_marp_rtl.py::test_qracc_with_onnx_single_node[verilator-1]' \
  'tests/test_marp_rtl.py::test_qracc_with_onnx_single_node[verilator-4]' \
  -q --tb=short"
```

## 7. Related

* `docs/REPORT_multibit_datapath_consolidated.md` §7.
* `docs/CRITIQUE_unsigned_multibit_input_conventions.md` — activation-width
  conventions shared by both paths.
