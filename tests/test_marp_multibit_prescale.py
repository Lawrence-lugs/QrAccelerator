"""One-to-one validation of the pre-scaling MAC golden model against ONNX.

This test does **not** run the RTL / verilator.  It verifies that
:func:`tests.utils.qlinearconv_pre_scale_mac` reproduces the ONNX
``QLinearConv`` integer (pre-output-scale / zero-point) accumulator, which is
the quantity the RTL accumulates before ``<< adc_ref_range_shifts`` in
``rtl/seq_acc.sv``.

Two checks are performed:

* **Full precision (B=8)** -- the golden integer MAC is combined with the
  node's bias / scales and re-quantized to the node's uint8 output, then
  compared against the *real* model's intermediate tensor obtained through
  :func:`qracc_marp.onnx_tools.onnx_utils.get_intermediate_tensor_value`.
* **Reduced precision (B=2, 4)** -- the golden bit-plane / shift-add path is
  compared against an ONNX ``QLinearConv`` built with the same B-bit
  quantized weights (identity scales) so the integer MAC is recovered
  directly.

Off-by-one rounding is tolerated.  The pass criterion is ``SNR > 30 dB`` (and
``max |diff| <= 1`` for the full-precision reconstruction).
"""

import os
import sys

import numpy as np
import onnx
import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from qracc_marp.mapping import core
from qracc_marp.onnx_tools import onnx_utils
from qracc_marp.quantization.quant import quantize_int8_to_bits

from .utils import qlinearconv_pre_scale_mac, save_scatter_fig

MODEL_PATH = os.path.join(REPO_ROOT, 'onnx_models', 'mbv2_cifar10_int8.onnx')
NODE_NAME = '/features/features.0/features.0.0/Conv_quant'
SNR_THRESHOLD_DB = 30.0


def _initializer(model, name):
    for init in model.graph.initializer:
        if init.name == name:
            return onnx.numpy_helper.to_array(init)
    raise AssertionError(f'initializer {name!r} not found')


def _find_node(model, name):
    for node in model.graph.node:
        if node.name == name:
            return node
    raise AssertionError(f'node {name!r} not found')


def _snr_db(expected, actual):
    """Signal-to-noise ratio in dB of *actual* against *expected*."""
    expected = np.asarray(expected, dtype=np.float64)
    actual = np.asarray(actual, dtype=np.float64)
    err = expected - actual
    err_pow = float(np.mean(err * err))
    if err_pow <= 0.0:
        return float('inf')
    sig_pow = float(np.mean(expected * expected))
    return 10.0 * np.log10(sig_pow / err_pow)


def _random_input(num_channels, seed):
    rng = np.random.RandomState(seed)
    return rng.randint(0, 256, (1, num_channels, 32, 32)).astype(np.uint8)


@pytest.fixture(scope='module')
def conv_ctx():
    """Resolved node / weight / scale context for the target QLinearConv."""
    model = onnx.load(MODEL_PATH)
    node = _find_node(model, NODE_NAME)
    mapping = core.NxModelMapping(
        model, imc_core_size=(256, 256), dwc_core_size=32
    )
    mnode = next(mn for mn in mapping.mapped_nodes if mn.name == NODE_NAME)

    input_name = node.input[0]
    weights = _initializer(model, node.input[3]).astype(np.int64)
    return {
        'model': model,
        'node': node,
        'mnode': mnode,
        'input_name': input_name,
        'output_tensor': node.output[0],
        'weights': weights,
        'x_scale': float(_initializer(model, node.input[1])),
        'x_zp': int(_initializer(model, node.input[2])),
        'w_scale': _initializer(model, node.input[4]).astype(np.float64),
        'y_scale': float(_initializer(model, node.input[6])),
        'y_zp': int(_initializer(model, node.input[7])),
        'bias': _initializer(model, node.input[8]).astype(np.int64),
    }


def _onnx_integer_mac(ctx, input_tensor, weights_int8, reference):
    """Integer MAC recovered from a synthetic identity-scale QLinearConv.

    The single-node model uses the given (already quantized) int8 weights with
    ``input_scale = weight_scale = 1.0`` so its dequantized output equals the
    integer accumulator ``sum((x - x_zp) * w)``.  ``reference`` is only used to
    pick a lossless dynamic range for the uint8 output.
    """
    ref = np.asarray(reference, dtype=np.float64)
    lo, hi = float(ref.min()), float(ref.max())
    span = max(hi - lo, 1.0)
    # Use 200 of the 256 uint8 levels, leaving a margin so nothing clips.
    y_scale = span / 200.0
    y_zp = int(np.clip(np.round(-lo / y_scale) + 28.0, 0, 255))

    node = onnx.NodeProto()
    node.CopyFrom(ctx['node'])
    del node.input[:]
    node.input.extend([
        ctx['input_name'], 'in_scale', 'in_zp',
        'W', 'W_scale', 'W_zp', 'Y_scale', 'Y_zp',
    ])
    del node.output[:]
    node.output.append('Y')

    initializers = {
        'in_scale': np.array(1.0, np.float32),
        'in_zp': np.array(ctx['x_zp'], np.uint8),
        'W': weights_int8.astype(np.int8),
        'W_scale': np.array(1.0, np.float32),
        'W_zp': np.array(0, np.int8),
        'Y_scale': np.array(y_scale, np.float32),
        'Y_zp': np.array(y_zp, np.uint8),
    }
    model = onnx_utils.make_single_node_model(
        node, initializers,
        input_names=[ctx['input_name']], output_names=['Y'],
    )
    out = onnx_utils.infer(model, {ctx['input_name']: input_tensor})[0]
    if out.ndim == 4:
        out = out[0]
    acc = (out.astype(np.float64) - y_zp) * y_scale  # (O, H, W)
    # (O, H, W) -> (H*W, O) to match the golden layout (row = y*W + x).
    return acc.transpose(1, 2, 0).reshape(-1, acc.shape[0])


@pytest.mark.parametrize('input_seed', [0, 1, 2, 3, 4])
def test_golden_matches_onnx_full_precision(conv_ctx, input_seed, figures):
    """Golden integer MAC + bias/scales reproduces the real ONNX output."""
    ctx = conv_ctx
    num_channels = ctx['weights'].shape[1]
    input_tensor = _random_input(num_channels, input_seed)

    golden = qlinearconv_pre_scale_mac(
        ctx['mnode'], input_tensor, adc_bits=32, weight_bits=8
    )

    y_q = np.asarray(onnx_utils.get_intermediate_tensor_value(
        MODEL_PATH, ctx['output_tensor'], {ctx['input_name']: input_tensor}
    ))
    if y_q.ndim == 4:
        y_q = y_q[0]

    num_out, height, width = y_q.shape
    mac = golden.reshape(height, width, num_out).transpose(2, 0, 1)
    int_acc = mac + ctx['bias'][:, None, None]
    real = int_acc * (ctx['x_scale'] * ctx['w_scale'][:, None, None])
    y_pred = np.clip(
        np.rint(real / ctx['y_scale']) + ctx['y_zp'], 0, 255
    )

    diff = np.abs(y_pred.astype(np.int64) - y_q.astype(np.int64))
    snr = _snr_db(y_q, y_pred)
    print(f'[B=8 seed={input_seed}] max|diff|={diff.max()} SNR={snr:.2f} dB')

    save_scatter_fig(
        y_q.astype(np.float64), y_pred.astype(np.float64),
        f'Golden vs ONNX QLinearConv output (B=8, seed={input_seed})',
        f'multibit_prescale_B8_seed{input_seed}', enabled=figures,
    )

    assert diff.max() <= 1, (
        f'full-precision golden deviates from ONNX by {diff.max()} '
        f'(> 1) for seed {input_seed}'
    )
    assert snr > SNR_THRESHOLD_DB, (
        f'full-precision SNR {snr:.2f} dB <= {SNR_THRESHOLD_DB} dB '
        f'for seed {input_seed}'
    )


@pytest.mark.parametrize('weight_bits', [2, 4])
@pytest.mark.parametrize('input_seed', [0, 1])
def test_golden_matches_onnx_reduced_precision(
    conv_ctx, weight_bits, input_seed, figures
):
    """Bit-plane / shift-add golden matches ONNX with B-bit weights."""
    ctx = conv_ctx
    num_channels = ctx['weights'].shape[1]
    input_tensor = _random_input(num_channels, input_seed)

    golden = qlinearconv_pre_scale_mac(
        ctx['mnode'], input_tensor, adc_bits=32, weight_bits=weight_bits
    )

    weights_b = quantize_int8_to_bits(
        ctx['weights'], weight_bits, signed=True
    )
    onnx_mac = _onnx_integer_mac(ctx, input_tensor, weights_b, golden)

    golden_f = golden.astype(np.float64)
    diff = np.abs(golden_f - onnx_mac)
    snr = _snr_db(onnx_mac, golden_f)
    print(
        f'[B={weight_bits} seed={input_seed}] max|diff|={diff.max():.2f} '
        f'SNR={snr:.2f} dB'
    )

    save_scatter_fig(
        onnx_mac, golden_f,
        f'Golden vs ONNX integer MAC (B={weight_bits}, seed={input_seed})',
        f'multibit_prescale_B{weight_bits}_seed{input_seed}',
        enabled=figures,
    )

    assert snr > SNR_THRESHOLD_DB, (
        f'B={weight_bits} seed={input_seed}: SNR {snr:.2f} dB <= '
        f'{SNR_THRESHOLD_DB} dB'
    )
