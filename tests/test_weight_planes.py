import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import onnx
import pytest

import qracc_marp.quantization.quant as quant


def test_b1_unsigned_matches_binary():
    rng = np.random.default_rng(0)
    w = rng.integers(0, 2, size=(8, 16), dtype=np.int8)
    planes = quant.weight_bit_planes(w, B=1, signed=False)
    assert planes.shape == (8, 8, 16)
    assert np.array_equal(planes[0], w.astype(np.uint8))
    for b in range(1, 8):
        assert np.all(planes[b] == 0)


def test_reconstruction_signed():
    rng = np.random.default_rng(42)
    w = rng.integers(-128, 128, size=(16, 32), dtype=np.int8)
    for B in (2, 4, 8):
        planes = quant.weight_bit_planes(w, B=B, signed=True)
        q = quant.quantize_int8_to_bits(w, B=B, signed=True)
        r = np.zeros_like(q, dtype=np.int64)
        for b in range(B):
            if b == B - 1 and B > 1:
                r = r - planes[b].astype(np.int64) * (1 << b)
            else:
                r = r + planes[b].astype(np.int64) * (1 << b)
        assert np.array_equal(r, q)


def test_range():
    rng = np.random.default_rng(7)
    w = rng.integers(-128, 128, size=(16, 32), dtype=np.int8)
    for B in (2, 4, 8):
        q = quant.quantize_int8_to_bits(w, B=B, signed=True)
        min_val = -(2 ** (B - 1))
        max_val = 2 ** (B - 1) - 1
        assert np.all(q >= min_val)
        assert np.all(q <= max_val)


def test_invalid_B():
    w = np.zeros((4, 4), dtype=np.int8)
    with pytest.raises(ValueError):
        quant.quantize_int8_to_bits(w, B=3, signed=True)


def test_b8_planes_reconstruct_onnx_int8():
    """B=8 signed bit-planes reconstruct the ONNX int8 weight exactly."""
    model_path = os.path.join(os.path.dirname(__file__), "..", "onnx_models", "mbv2_cifar10_int8.onnx")
    model = onnx.load(model_path)
    target = None
    for node in model.graph.node:
        if node.name == "/features/features.0/features.0.0/Conv_quant":
            target = node
            break
    assert target is not None, "Conv_quant node not found"
    init_by_name = {init.name: init for init in model.graph.initializer}
    w = onnx.numpy_helper.to_array(init_by_name[target.input[3]])
    assert w.dtype == np.int8
    assert w.shape == (32, 3, 3, 3)
    planes = quant.weight_bit_planes(w, 8, True)
    r = np.zeros_like(w, dtype=np.int64)
    for b in range(8):
        term = planes[b].astype(np.int64) * (1 << b)
        if b == 7:  # MSB / sign bit is negated for signed
            r = r - term
        else:
            r = r + term
    assert np.array_equal(r, w.astype(np.int64))


def test_b2_b4_planes_reconstruct_quantized():
    """B=2 and B=4 signed bit-planes reconstruct quantize_int8_to_bits exactly."""
    model_path = os.path.join(os.path.dirname(__file__), "..", "onnx_models", "mbv2_cifar10_int8.onnx")
    model = onnx.load(model_path)
    target = None
    for node in model.graph.node:
        if node.name == "/features/features.0/features.0.0/Conv_quant":
            target = node
            break
    assert target is not None, "Conv_quant node not found"
    init_by_name = {init.name: init for init in model.graph.initializer}
    w = onnx.numpy_helper.to_array(init_by_name[target.input[3]])
    for B in (2, 4):
        planes = quant.weight_bit_planes(w, B, True)
        q = quant.quantize_int8_to_bits(w, B, True)
        r = np.zeros_like(q, dtype=np.int64)
        for b in range(B):
            term = planes[b].astype(np.int64) * (1 << b)
            if b == B - 1:  # MSB / sign bit is negated for signed
                r = r - term
            else:
                r = r + term
        assert np.array_equal(r, q)


def test_pack_weight_planes_reconstruct_quantized():
    """Emitter words (B=2,4,8) unpack and recombine to quantize_int8_to_bits output."""
    from qracc_marp.compile.compile import pack_weight_planes

    rng = np.random.default_rng(3)
    w = rng.integers(-128, 128, size=(32, 32), dtype=np.int8)
    n_bits = w.size
    for B in (2, 4, 8):
        words = pack_weight_planes(w, B=B, signed=True)
        # Words are flat [bank_row, plane]: index i -> bank row i//8, plane i%8.
        planes_out = np.zeros((B, n_bits), dtype=np.uint8)
        for i, word in enumerate(words):
            plane = i % 8
            bank_row = i // 8
            if plane >= B:
                continue
            for c in range(32):
                f = bank_row * 32 + c
                if f < n_bits:
                    planes_out[plane, f] = (int(word) >> c) & 1
        planes_out = planes_out.reshape((B,) + w.shape)
        r = np.zeros_like(w, dtype=np.int64)
        for b in range(B):
            term = planes_out[b].astype(np.int64) * (1 << b)
            if b == B - 1:  # MSB / sign bit is negated for signed
                r = r - term
            else:
                r = r + term
        q = quant.quantize_int8_to_bits(w, B, signed=True)
        assert np.array_equal(r, q)


def test_pack_weight_planes_reconstruct_onnx_b8():
    """B=8 emitter words reconstruct the real ONNX int8 Conv weight exactly."""
    from qracc_marp.compile.compile import pack_weight_planes

    model_path = os.path.join(os.path.dirname(__file__), "..", "onnx_models", "mbv2_cifar10_int8.onnx")
    model = onnx.load(model_path)
    target = None
    for node in model.graph.node:
        if node.name == "/features/features.0/features.0.0/Conv_quant":
            target = node
            break
    assert target is not None, "Conv_quant node not found"
    init_by_name = {init.name: init for init in model.graph.initializer}
    w = onnx.numpy_helper.to_array(init_by_name[target.input[3]])
    assert w.dtype == np.int8
    words = pack_weight_planes(w, B=8, signed=True)
    n_bits = w.size
    planes_out = np.zeros((8, n_bits), dtype=np.uint8)
    for i, word in enumerate(words):
        plane = i % 8
        bank_row = i // 8
        for c in range(32):
            f = bank_row * 32 + c
            if f < n_bits:
                planes_out[plane, f] = (int(word) >> c) & 1
    planes_out = planes_out.reshape((8,) + w.shape)
    r = np.zeros_like(w, dtype=np.int64)
    for b in range(8):
        term = planes_out[b].astype(np.int64) * (1 << b)
        if b == 7:  # MSB / sign bit is negated for signed
            r = r - term
        else:
            r = r + term
    assert np.array_equal(r, w.astype(np.int64))
