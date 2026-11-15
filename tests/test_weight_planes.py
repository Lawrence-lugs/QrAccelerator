import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
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
