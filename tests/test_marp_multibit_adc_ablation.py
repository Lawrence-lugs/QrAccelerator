"""Ablation of the flash-ADC precision and range shift (fixed-full-scale model).

Pure numpy/onnx - no simulator and no compiler.  For the first MobileNetV2
layer (and every weight width ``B``) this prints the SNR of the per-plane ADC
emulation of ``rtl/ts_qracc.sv`` against the exact integer MAC, as a function
of

* ``bits`` - comparator count (the hardware is fixed at 4; wider converters are
  evaluated only to show what a future revision would buy), and
* ``s``    - ``cfg.adc_ref_range_shifts``.

Semantics under test (see ``PLAN_adc_range_model_correction.md`` and the
comment block in ``rtl/ts_qracc.sv``): the ladder has a *fixed* full scale and
``s`` **halves the span toward V_RST**, so the LSB is
``fs_counts / 2**(bits-1+s)`` -- finer with larger ``s``, saturating earlier.
This is the inverse of the pre-2026-11-18 model, which is kept as
``quant.adc_quantize_legacy`` for reproducing old captures.

The tests pin four things so the model cannot drift silently:
  1. the LSB/span relation of the quantiser,
  2. that the bipolar ladder (`mbl = 2P - A_j`) and a power-of-two full scale
     are what make a 4-comparator converter usable here (with an LSB of exactly
     2 counts the rounding is almost lossless, because `A_j`'s parity is shared
     by every plane of a window),
  3. that the chooser returns the best candidate inside its clip budget,
  4. that the legacy final-clip mode ("quantise the MAC to 4 bits") is useless.
"""

import os
import sys

import numpy as np
import onnx
import pytest

marp = pytest.importorskip("qracc_marp")
import qracc_marp.quantization.quant as quant
from qracc_marp.compile import compute
from qracc_marp.compile.stimulus_gen import (
    _activation_bit_counts,
    _bitplane_partials,
    infer_adc_config,
)
from qracc_marp.mapping import core

from .utils import qlinearconv_pre_scale_mac

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

MODEL_PATH = os.path.join(REPO_ROOT, 'onnx_models', 'mbv2_cifar10_int8.onnx')
NODE_NAME = '/features/features.0/features.0.0/Conv_quant'


def snr_db(expected, actual):
    expected = np.asarray(expected, dtype=np.float64)
    actual = np.asarray(actual, dtype=np.float64)
    var_err = float(np.var(expected - actual))
    if var_err <= 0:
        return float("inf")
    return 10.0 * np.log10(float(np.var(expected)) / var_err)


@pytest.fixture(scope="module")
def conv_ctx():
    nx_model = onnx.load(MODEL_PATH)
    mapping = core.NxModelMapping(
        nx_model, imc_core_size=(256, 256), dwc_core_size=32)
    node = next(mn for mn in mapping.mapped_nodes if mn.name == NODE_NAME)
    np.random.seed(0)
    input_tensor = np.random.randint(0, 256, (1, 3, 32, 32)).astype(np.uint8)
    return node, input_tensor, nx_model


def _toeplitz(node, input_tensor):
    return compute.toeplitzize_input(
        in_tensor=input_tensor.squeeze(0),
        kernel_shape=node.kernel.shape,
        strides=node.strides,
        pads=node.pads,
        zero_point=int(node.x_zp),
        channel_minor=True,
    )


def _weights_toeplitz(node):
    """Weights in the same row order as the toeplitz columns.

    ``node.matrix`` is the SRAM-side matrix (rows permuted for the bank
    interleave), so it cannot be dotted with this toeplitz directly.  The
    chooser only cares about the weight statistics, but the cross-check against
    the golden MAC needs the matching order.
    """
    kernel = node.kernel
    O = kernel.shape[0]
    return kernel.transpose(0, 3, 1, 2).reshape(O, -1).T.astype(np.int64)


def test_quantiser_lsb_and_span():
    """`s` halves the span toward V_RST: LSB = fs / 2**(bits-1+s)."""
    for bits in (4, 5, 6):
        for s in (0, 1, 2):
            fs = 32.0
            lsb = fs / float(1 << (bits - 1 + s))
            # A ramp at half-LSB spacing must map to consecutive codes.
            ramp = np.arange(-4, 5, dtype=np.int64) * lsb
            codes = quant.adc_quantize(ramp, adc_bits=bits, shift=s,
                                       fs_counts=fs)
            assert np.all(np.diff(codes) == 1)
            # Saturation happens `2**s` counts earlier than at s=0.
            span = lsb * ((1 << (bits - 1)) - 1)
            lo = lsb * (1 << (bits - 1))
            assert quant.adc_quantize(np.array([span + lsb, -lo - lsb]),
                                      adc_bits=bits, shift=s,
                                      fs_counts=fs).tolist() == [
                (1 << (bits - 1)) - 1, -(1 << (bits - 1))]
            assert span == fs / float(1 << s) * (
                ((1 << (bits - 1)) - 1) / float(1 << (bits - 1)))


def test_bipolar_ladder_uses_the_whole_range(conv_ctx):
    """The bipolar matrix (mbl = 2P - A_j) beats the unipolar one."""
    node, input_tensor, _ = conv_ctx
    toe = _toeplitz(node, input_tensor)
    bipolar = infer_adc_config(toe, _weights_toeplitz(node), weight_bits=8,
                               adc_bits=4,
                               ladder="bipolar", max_sample_rows=0)
    binary = infer_adc_config(toe, _weights_toeplitz(node), weight_bits=8,
                              adc_bits=4,
                              ladder="binary", max_sample_rows=0)
    print(f"bipolar s={bipolar['s']} lsb={bipolar['lsb_counts']:.2f} "
          f"clip={bipolar['clip_frac']*100:.2f}% snr={bipolar['snr_db']:.2f} dB")
    print(f"binary  s={binary['s']} lsb={binary['lsb_counts']:.2f} "
          f"clip={binary['clip_frac']*100:.2f}% snr={binary['snr_db']:.2f} dB")
    assert bipolar["snr_db"] > binary["snr_db"] + 3.0


@pytest.mark.parametrize("weight_bits", [2, 4, 8])
def test_adc_ablation_table(conv_ctx, weight_bits):
    """Print the bits x range-shift table and pin the 4-bit ceiling."""
    node, input_tensor, _ = conv_ctx
    toe = _toeplitz(node, input_tensor)

    cfg = infer_adc_config(
        toe, _weights_toeplitz(node), weight_bits=weight_bits, adc_bits=4,
        ladder="bipolar", max_sample_rows=0,
        preview_bits=(4, 5, 6, 7, 8),
    )
    partials = _bitplane_partials(toe, _weights_toeplitz(node), 8, weight_bits,
                                 max_sample_rows=0)
    acts = _activation_bit_counts(toe, 8, max_sample_rows=0)
    allp = np.stack([p for row in partials for p in row])
    allmbl = np.stack([2 * p - acts[j][:, None]
                       for j, row in enumerate(partials) for p in row])
    print(f"\nB={weight_bits}: partial mean={allp.mean():.2f} "
          f"sigma={allp.std():.2f} max={allp.max()}  "
          f"mbl sigma={allmbl.std():.2f} max|mbl|={np.abs(allmbl).max()}  "
          f"fs={cfg['fs_counts']:.0f}")
    print(f"{'bits':>4} {'s':>2} {'lsb':>6} {'clip%':>6} {'snr':>7}")
    for bits, cands in cfg["candidates"].items():
        for c in cands:
            print(f"{bits:4d} {c['s']:2d} {c['lsb_counts']:6.2f} "
                  f"{c['clip_frac']*100:6.2f} {c['snr_db']:7.2f}")

    # (a) the 4-bit converter is usable here (the bipolar ladder plus a
    #     power-of-two full scale is what buys the accuracy).
    best4 = max(c["snr_db"] for c in cfg["candidates"][4])
    assert 10.0 < best4 < 200.0, best4
    # (b) more comparators do buy accuracy (preview is advisory only).
    best8 = max(c["snr_db"] for c in cfg["candidates"][8])
    assert best8 >= best4

    # (c) the golden model agrees with the chooser's score on the same config.
    from .utils import qlinearconv_prescale_snr
    ref = qlinearconv_prescale_snr(
        node, input_tensor, weight_bits=weight_bits,
        adc_shift=cfg["s"], adc_bits=cfg["bits"], ladder="bipolar",
        fs_counts=cfg["fs_counts"],
    )
    print(f"chooser snr={cfg['snr_db']:.3f} dB  golden snr={ref['snr_db']:.3f} "
          f"dB (calibrated {ref['snr_affine_db']:.3f} dB)")
    assert ref["snr_db"] == pytest.approx(cfg["snr_db"], abs=0.05)


@pytest.mark.parametrize("weight_bits", [2, 4, 8])
def test_legacy_final_clip_is_unusable(conv_ctx, weight_bits):
    """Quantising the *final* MAC to 4 bits destroys the result."""
    node, input_tensor, _ = conv_ctx
    exact = qlinearconv_pre_scale_mac(
        node, input_tensor, adc_bits=32, weight_bits=weight_bits,
        adc_mode="none", unfold=True,
    )
    clipped = qlinearconv_pre_scale_mac(
        node, input_tensor, adc_bits=4, weight_bits=weight_bits,
        adc_mode="output", unfold=True,
    )
    snr = snr_db(exact, clipped)
    print(f"B={weight_bits}: legacy final-clip SNR={snr:.3f} dB")
    assert snr < 3.0


@pytest.mark.parametrize("weight_bits", [2, 4, 8])
def test_shift_chooser_picks_best_range(conv_ctx, weight_bits):
    """The chosen shift is the best candidate inside the clip budget."""
    node, input_tensor, _ = conv_ctx
    toe = _toeplitz(node, input_tensor)
    cfg = infer_adc_config(toe, _weights_toeplitz(node), weight_bits=weight_bits,
                           adc_bits=4, ladder="bipolar", max_sample_rows=0,
                           saturation_budget=0.05)
    cands = cfg["candidates"][cfg["bits"]]
    ok = [c for c in cands if c["clip_frac"] <= 0.05]
    assert ok, "no candidate inside the saturation budget"
    best = max(c["snr_db"] for c in ok)
    assert cfg["snr_db"] == pytest.approx(best, abs=1e-9)
    assert cfg["clip_frac"] <= 0.05
    assert 0 <= cfg["s"] <= 6
