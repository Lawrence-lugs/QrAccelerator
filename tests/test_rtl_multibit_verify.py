"""RTL verification of the multi-bit datapath fixes.

Unit-level bit-exact checks for the corrected ADC model and the bipolar bias
subtractor, plus the seq_acc datapath and SRAM matrix-order checks.

Everything here runs under Verilator inside the devcontainer:

    pytest tests/test_rtl_multibit_verify.py --simulator verilator
"""

import os
import re

import numpy as np
import pytest

import qracc_marp.quantization.quant as q
from . import utils as test_utils
from .utils import run_simulation

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _parse_adc_log(log_path):
    pat = re.compile(
        r'\[ADC\] n=(\d+) fs=(\d+) mode=(\d+) s=(\d+) '
        r'mbl=(-?\d+) code=(-?\d+) therm=(-?\d+)')
    rows = []
    with open(log_path, errors='replace') as f:
        for line in f:
            m = pat.search(line)
            if m:
                rows.append(tuple(int(m.group(i)) for i in range(1, 8)))
    return rows


@pytest.mark.needs_verilator
@pytest.mark.parametrize(
    'numAdcBits,adcFullScale',
    [
        (4, 16),    # default full scale
        (4, 32),    # legacy 1-bit configuration (LSB = 2 at s = 1)
        (12, 2048),  # LSB = 1 at s = 0: exact integer path
        (12, 4096),  # LSB = 2 at s = 0: rounding path
    ],
)
def test_ts_qracc_adc(simulator, numAdcBits, adcFullScale):
    """ts_qracc must match quant.adc_quantize bit-exactly."""
    package_list = ['../rtl/qracc_pkg.svh']
    rtl_file_list = ['../rtl/ts_qracc.sv']
    tb_name = 'tb_ts_qracc'
    tb_file = f'../tb/ts_qracc/{tb_name}.sv'
    log_file = f'tests/logs/{tb_name}_{simulator}.log'
    os.makedirs(os.path.dirname(log_file), exist_ok=True)

    parameters = {
        'SRAM_ROWS': 64,
        'SRAM_COLS': 1,
        'numAdcBits': numAdcBits,
        'adcFullScale': adcFullScale,
    }

    run_simulation(simulator, parameters, package_list, tb_file,
                   test_utils.sim_args, rtl_file_list, log_file, run=True,
                   top_module=tb_name)

    rows = _parse_adc_log(log_file)
    assert rows, 'no [ADC] lines found in the simulation log'
    assert len(rows) == 2 * 9 * (2 * 64 + 1), (
        f'expected {2 * 9 * (2 * 64 + 1)} ADC samples, got {len(rows)}')

    for n, fs, mode, s, mbl, code, therm in rows:
        ladder = 'binary' if mode else 'bipolar'
        expected = int(q.adc_quantize(
            mbl, adc_bits=n, shift=s, fs_counts=fs, mode=ladder))
        assert code == expected, (
            f'ADC mismatch n={n} fs={fs} mode={ladder} s={s} mbl={mbl}: '
            f'RTL code {code}, golden {expected}')
        assert therm == code, (
            f'thermometer decode mismatch n={n} fs={fs} mode={ladder} '
            f's={s} mbl={mbl}: ADC_CODE {code}, ADC_OUT decode {therm}')


@pytest.mark.needs_verilator
@pytest.mark.parametrize('inputTrits', [1, 2, 4, 7, 8])
def test_bipolar_bias_sub(simulator, inputTrits, numTrials=32, seed=0):
    """bipolar_bias_sub must equal sum_j A_j << j bit-exactly."""
    rng = np.random.default_rng(seed)
    a = rng.integers(0, 128, size=(numTrials, inputTrits), dtype=np.int64)
    expected = np.zeros(numTrials, dtype=np.int64)
    for j in range(inputTrits):
        expected += a[:, j] << j

    in_dir = 'tb/bipolar_bias_sub/inputs'
    out_dir = 'tb/bipolar_bias_sub/outputs'
    os.makedirs(in_dir, exist_ok=True)
    os.makedirs(out_dir, exist_ok=True)
    np.savetxt(f'{in_dir}/a.txt', a, fmt='%d')

    package_list = ['../rtl/qracc_pkg.svh']
    rtl_file_list = ['../rtl/bipolar_bias_sub.sv']
    tb_name = 'tb_bipolar_bias_sub'
    tb_file = f'../tb/bipolar_bias_sub/{tb_name}.sv'
    log_file = f'tests/logs/{tb_name}_{simulator}.log'
    os.makedirs(os.path.dirname(log_file), exist_ok=True)

    parameters = {
        'inputTrits': inputTrits,
        'numTrials': numTrials,
        'accumulatorBits': 16,
    }

    run_simulation(simulator, parameters, package_list, tb_file,
                   test_utils.sim_args, rtl_file_list, log_file, run=True,
                   top_module=tb_name)

    actual = np.loadtxt(f'{out_dir}/bias_rtl.txt', dtype=np.int64, ndmin=1)
    assert actual.shape == expected.shape, (
        f'expected {expected.shape} bias samples, got {actual.shape}')
    assert np.array_equal(actual, expected), (
        f'bias mismatch for T={inputTrits}:\n'
        f'first mismatch at {np.flatnonzero(actual != expected)[:5]}\n'
        f'RTL     {actual[:8]}\nexpected {expected[:8]}')


def _seq_acc_multibit_reference(x, wB, weight_bits, adc_bits,
                                adc_full_scale, adc_shift, unsigned_acts=False):
    """Bit-exact reference for the corrected bipolar seq_acc path.

    Returns ``2*MAC`` in the accumulator units seq_acc publishes (before its
    ``<< adc_ref_range_shifts``), matching ``(lsb*acc - bias)``.
    """
    rows, cols = wB.shape
    batches = x.shape[0]
    # Unsigned 8-bit uses input_bits = 9 -> 8 trits; signed uses 7.
    input_trits = 8 if unsigned_acts else 7
    lsb = adc_full_scale / float(1 << (adc_bits - 1 + adc_shift))

    if unsigned_acts:
        p_bits = [(((x >> j) & 1) != 0).astype(np.int64)
                  for j in range(input_trits)]
        n_bits = [np.zeros_like(x, dtype=np.int64)
                  for _ in range(input_trits)]
        bias = x.sum(axis=1).astype(np.int64)
    else:
        # Two's-complement activation magnitudes, as twos_to_bipolar produces.
        mag = np.abs(x)
        p_bits = [(((x >= 0) & ((mag >> j) & 1)) != 0).astype(np.int64)
                  for j in range(input_trits)]
        n_bits = [(((x < 0) & ((mag >> j) & 1)) != 0).astype(np.int64)
                  for j in range(input_trits)]
        bias = x.sum(axis=1).astype(np.int64)

    # The MSB plane is negated by shift_add_tree; planes >= B are ignored by
    # the RTL and must not be included here (wB is sign-extended).
    acc = np.zeros((batches, cols), dtype=np.int64)
    for j in range(input_trits):
        a_eff = p_bits[j].sum(axis=1) - n_bits[j].sum(axis=1)
        for b in range(weight_bits):
            plane = ((wB >> b) & 1).astype(np.int64)
            partial = p_bits[j] @ plane - n_bits[j] @ plane
            mbl = 2 * partial - a_eff[:, None]
            code = q.adc_quantize(
                mbl, adc_bits=adc_bits, shift=adc_shift,
                fs_counts=adc_full_scale, mode='bipolar')
            term = code << (j + b)
            if b == weight_bits - 1 and weight_bits > 1:
                term = -term
            acc += term
    return lsb * acc - bias[:, None]


@pytest.mark.needs_verilator
@pytest.mark.parametrize(
    'weight_bits,adc_bits,adc_full_scale,adc_shift,unsigned_acts,stream_macs',
    [
        (2, 12, 2048, 0, False, 0),
        (4, 12, 2048, 0, False, 0),
        (8, 12, 2048, 0, False, 0),
        (2, 4, 16, 0, False, 0),
        (4, 4, 16, 0, False, 0),
        (8, 4, 16, 0, False, 0),
        # R1 repro configuration: unsigned 8-bit activations -> 8 trits.
        (2, 12, 2048, 0, True, 0),
        (8, 4, 16, 0, True, 0),
        # Back-to-back streaming (top-level controller), same R1 config.
        (8, 4, 16, 0, True, 1),
    ],
)
def test_seq_acc_multibit(simulator, weight_bits, adc_bits, adc_full_scale,
                          adc_shift, unsigned_acts, stream_macs, seed=0):
    """Multi-bit signed seq_acc: bit-exact against the per-plane golden.

    With a 12-bit converter and ``lsb = 1`` the ADC is out of the loop and the
    check is purely datapath + bias.  The 4-bit cases compare against the exact
    corrected ADC model (including saturation).
    """
    rows, cols, batches = 16, 16, 4
    rng = np.random.default_rng(seed)
    w_int8 = rng.integers(-127, 128, size=(rows, cols), dtype=np.int64)
    if unsigned_acts:
        # Full 8-bit range: exercises all eight PISO trits (the top-level
        # prestack test uses uint8 activations).
        x = rng.integers(0, 256, size=(batches, rows), dtype=np.int64)
    else:
        x = rng.integers(-3, 4, size=(batches, rows), dtype=np.int64)
    wB = q.quantize_int8_to_bits(w_int8, weight_bits, signed=True)

    num_planes = 8
    plane_words = np.zeros((rows, num_planes), dtype=object)
    for r in range(rows):
        for b in range(num_planes):
            bits = ((wB[r] >> b) & 1).astype(np.int64)
            plane_words[r, b] = int(sum(int(v) << c for c, v in enumerate(bits)))
    plane_words = plane_words.astype(np.int64)

    in_dir = 'tb/seq_acc/inputs'
    out_dir = 'tb/seq_acc/outputs'
    os.makedirs(in_dir, exist_ok=True)
    os.makedirs(out_dir, exist_ok=True)
    np.savetxt(f'{in_dir}/w.txt', plane_words, fmt='%d')
    np.savetxt(f'{in_dir}/x.txt', x, fmt='%d')
    np.savetxt(f'{in_dir}/wx_clipped.txt', np.zeros((batches, cols), dtype=int),
               fmt='%d')

    package_list = ['../rtl/qracc_pkg.svh']
    rtl_file_list = [
        '../rtl/qr_acc_wrapper.sv',
        '../rtl/bipolar_bias_sub.sv',
        '../rtl/seq_acc.sv',
        '../rtl/shift_add_tree.sv',
        '../rtl/ts_qracc.sv',
        '../rtl/wr_controller.sv',
        '../rtl/twos_to_bipolar.sv',
    ]
    tb_name = 'tb_seq_acc'
    tb_file = '../tb/seq_acc/tb_seq_acc.sv'
    log_file = f'tests/logs/{tb_name}_multibit_{weight_bits}_{adc_bits}.log'
    os.makedirs(os.path.dirname(log_file), exist_ok=True)

    parameters = [
        f'SRAM_ROWS={rows}',
        f'SRAM_COLS={cols}',
        'xBits=8',
        f'xBatches={batches}',
        f'numAdcBits={adc_bits}',
        f'adcFullScale={adc_full_scale}',
        f'adcShift={adc_shift}',
        'macMode=0',
        'outBits=8',
        f'unsignedActs={int(unsigned_acts)}',
        f'weightBits={weight_bits}',
        'weightSigned=1',
        'weightPlanes=1',
        'accumulatorBits=32',
        f'streamMacs={stream_macs}',
    ]

    run_simulation(simulator, parameters, package_list, tb_file,
                   test_utils.sim_args, rtl_file_list, log_file, run=True,
                   top_module=tb_name)

    actual = np.loadtxt(f'{in_dir}/mac_out_rtl_bipolar.txt',
                        dtype=np.int64, ndmin=2)
    expected = _seq_acc_multibit_reference(
        x, wB, weight_bits, adc_bits, adc_full_scale, adc_shift,
        unsigned_acts=unsigned_acts)
    expected = expected.astype(np.int64)
    expected = expected << adc_shift

    assert actual.shape == expected.shape, (
        f'expected {expected.shape} MAC samples, got {actual.shape}')
    assert np.array_equal(actual, expected), (
        f'B={weight_bits} adc={adc_bits} fs={adc_full_scale} s={adc_shift}: '
        f'{int(np.count_nonzero(actual != expected))} mismatches\n'
        f'first rows RTL:\n{actual[:2]}\nexpected:\n{expected[:2]}')
