"""Unit test for rtl/wsacc/wsacc_pe_cluster.sv digital WSAcc depthwise path on a real layer.

Loads the exact weight words emitted by the MARP compiler for mnode 1
(depthwise, 32 channels, 3x3, cin=1 per group; initializer onnx::Conv_543_quantized,
shape (32,1,3,3)) into tb/wsacc/tb_wsacc_dw32.sv via $readmemh, feeds 4 real 3x3
ifmap window positions taken from a small random uint8 ifmap (built in the same
window order as the MARP compile), and asserts each PE's data_o equals the
numpy-equivalent depthwise sum of signed int8 weight * unsigned activation.
Compiles with verilator (numPes=32, windowElements=9, dataWidth=8,
outputWidth=16, weightInterfaceWidth=32) and asserts exit 0 and 'TB_PASS'.
The test runs ONLY inside the container via the specified docker command.
"""

import subprocess
import os
import pytest

import numpy as np
import onnx

repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

tb_dir = os.path.join(repo_root, 'tb', 'wsacc')
rtl_dir = os.path.join(repo_root, 'rtl')
sims_dir = os.path.join(repo_root, 'sims')
onnx_path = os.path.join(repo_root, 'onnx_models', 'mbv2_cifar10_int8_binary.onnx')

tb_file = os.path.join(tb_dir, 'tb_wsacc_dw32.sv')

rtl_files = [
    os.path.join(rtl_dir, 'wsacc', 'wsacc_pe_cluster.sv'),
    os.path.join(rtl_dir, 'wsacc', 'wsacc_pe.sv'),
]

sim_args_verilator = [
    '--binary',
    '--timing',
    '-j', '4',
    '-sv',
    '+incdir+../rtl',
    '-Wno-fatal',
    '-Wno-WIDTHEXPAND',
    '-Wno-WIDTHTRUNC',
    '-Wno-UNUSEDSIGNAL',
    '-Wno-UNDRIVEN',
    '-Wno-UNUSEDPARAM',
    '-Wno-PINMISSING',
    '-Wno-GENUNNAMED',
    '-Wno-CASEINCOMPLETE',
    '-Wno-TIMESCALEMOD',
    '-Wno-IMPLICITSTATIC',
    '-Wno-LATCH',
    '-Wno-COMBDLY',
    '-Wno-BLKSEQ',
    '-Wno-INITIALDLY',
    '-CFLAGS', '-O1',
]

top_name = 'tb_wsacc_dw32'

NUM_PES = 32
WINDOW_ELEMENTS = 9
NUM_POSITIONS = 4


def _find_mnode1_weight(model):
    for i in model.graph.initializer:
        if i.name == 'Conv_543_quantized' or i.name.endswith('Conv_543_quantized'):
            return i
    # Fallback: any initializer with the depthwise weight shape (32,1,3,3).
    for i in model.graph.initializer:
        if list(i.dims) == [32, 1, 3, 3]:
            return i
    return None


def _generate_stimulus():
    """Return (weight_words, data_i, golden) built from the MARP compile output.

    weight_words : np.uint8? no, list of 72 uint32 words (9 taps x 8 words)
    data_i       : (NUM_POSITIONS, NUM_PES, WINDOW_ELEMENTS) uint8
    golden       : (NUM_POSITIONS, NUM_PES) int32  (fits int16)
    """
    from qracc_marp.compile.stimulus_gen import kernel_to_writes

    model = onnx.load(onnx_path)
    init = _find_mnode1_weight(model)
    assert init is not None, 'mnode 1 weight initializer Conv_543_quantized not found'
    assert list(init.dims) == [32, 1, 3, 3], list(init.dims)

    w = onnx.numpy_helper.to_array(init)  # (32,1,3,3) int8
    assert w.shape == (32, 1, 3, 3), w.shape

    # MARP depthwise weight write: physical_kernel.transpose(1,2,3,0) -> KHWC (1,3,3,32),
    # then kernel_to_writes(kernel_hwc, channels=32, hexes=False).
    # kernel_to_writes: kernel_flat = kernel.reshape(-1,32) -> (9 taps, 32 channels);
    # tap t = (kh=t/3, kw=t%3) row-major; each row split into 8 words of 4 channels;
    # word w packs channels [4w..4w+3] as byte0(LSB)=ch4w ... byte3(MSB)=ch4w+3.
    kernel_hwc = w.transpose(1, 2, 3, 0)  # (1,3,3,32)
    words = np.asarray(kernel_to_writes(kernel_hwc, channels=NUM_PES, hexes=False), dtype=np.uint32)
    assert len(words) == 9 * 8, len(words)

    # Signed int8 weight per PE c (== channel c) and tap t = kh*3+kw, derived
    # from the EXACT same word bytes the RTL loads via $readmemh (MARP compile output).
    # word[tap*8 + c/4] packs channels [4*(c/4)..4*(c/4)+3]; byte (c%4) (LSB i=0)
    # holds channel c. Sign-extend byte -> int8.
    def w_signed(c, t):
        word_idx = t * 8 + (c // 4)
        byte_idx = c % 4
        b = int((int(words[word_idx]) >> (byte_idx * 8)) & 0xFF)
        return b - 256 if b >= 128 else b

    # Small random uint8 ifmap (NHWC), zero-padded, 4 real 3x3 window positions.
    # Values 0..25 keep |sum| <= 9*128*25 = 28800 < 32767 so the int16 accumulator
    # cannot wrap; golden is bit-exact vs the RTL's 16-bit signed data_o.
    rng = np.random.default_rng(1234)
    ifmap = rng.integers(0, 26, size=(1, 5, 5, NUM_PES)).astype(np.uint8)  # NHWC
    padded = np.pad(ifmap, ((0, 0), (1, 1), (1, 1), (0, 0)), mode='constant', constant_values=0)
    positions = [(0, 0), (1, 1), (3, 3), (4, 4)]  # (oh, ow); corners exercise padding

    data_i = np.zeros((NUM_POSITIONS, NUM_PES, WINDOW_ELEMENTS), dtype=np.uint8)
    golden = np.zeros((NUM_POSITIONS, NUM_PES), dtype=np.int32)
    for p, (oh, ow) in enumerate(positions):
        for c in range(NUM_PES):
            for t in range(WINDOW_ELEMENTS):
                kh, kw = t // 3, t % 3          # tap t -> spatial offset (kh,kw), row-major
                data_i[p, c, t] = padded[0, oh + kh, ow + kw, c]
                golden[p, c] += w_signed(c, t) * int(data_i[p, c, t])

    return words, data_i, golden


def test_wsacc_dw32():
    os.makedirs(sims_dir, exist_ok=True)
    log_file = os.path.join(sims_dir, 'tb_wsacc_dw32.log')

    words, data_i, golden = _generate_stimulus()

    # Write stimulus files into the workspace (sims/) so the container-run TB can $readmemh them.
    with open(os.path.join(sims_dir, 'p9_dw_words.txt'), 'w') as f:
        for wd in words:
            f.write(f'{int(wd):08x}\n')
    with open(os.path.join(sims_dir, 'dw_data_i.txt'), 'w') as f:
        for p in range(NUM_POSITIONS):
            for c in range(NUM_PES):
                for t in range(WINDOW_ELEMENTS):
                    f.write(f'{int(data_i[p, c, t]):02x}\n')
    with open(os.path.join(sims_dir, 'dw_golden.txt'), 'w') as f:
        for p in range(NUM_POSITIONS):
            for c in range(NUM_PES):
                f.write(f'{int(golden[p, c]) & 0xffff:04x}\n')

    verilator_params = [
        '-GnumPes=32',
        '-GwindowElements=9',
        '-GdataWidth=8',
        '-GoutputWidth=16',
        '-GweightInterfaceWidth=32',
    ]

    compile_command = [
        'verilator',
        *rtl_files,
        tb_file,
    ] + sim_args_verilator + verilator_params + [
        '--top-module', top_name,
        '-o', top_name,
        '--Mdir', f'obj_dir_{top_name}',
    ]

    print(f'=====VERILATOR COMPILE COMMAND=====')
    print(' '.join(compile_command))

    with open(log_file, 'w+') as f:
        proc = subprocess.Popen(
            compile_command,
            shell=False,
            cwd=sims_dir,
            stdout=f,
            stderr=subprocess.STDOUT,
        )
    proc.wait()
    retval = proc.returncode
    assert retval == 0, f'Verilator compilation failed; see {log_file}'

    run_command = [f'./obj_dir_{top_name}/{top_name}']

    print(f'=====VERILATOR RUN COMMAND=====')
    print(' '.join(run_command))

    with open(log_file, 'a') as f:
        f.write('\n===== VERILATOR RUN COMMAND =====\n')
        f.write(' '.join(run_command))
        f.write('\n')
    sim = subprocess.Popen(
        run_command,
        shell=False,
        cwd=sims_dir,
        stdout=open(log_file, 'a'),
        stderr=subprocess.STDOUT,
    )
    sim.wait()
    retval = sim.returncode

    with open(log_file, 'r') as f:
        output = f.read()

    print(output)

    assert retval == 0, f'Simulation failed; see {log_file}'
    assert 'TB_PASS' in output, f'TB_PASS not found in output:\n{output}'


def _pack_depthwise_words_correct(w):
    """Correct depthwise packing: 4 channels per uint32 word.

    word[tap*8 + c//4] byte (c%4) == int8 w[c, 0, tap//3, tap%3] as uint8
    (two's complement). This matches the fixed MARP compile path
    (qracc_marp/compile/compile.py _get_weight_data, P10-DW) and the S3
    ONNX-weight check; it is NOT the legacy kernel_to_writes(uint8-shift)
    behavior that zeroed bytes 1-3.
    """
    kernel_hwc = w.transpose(1, 2, 3, 0)  # (1,3,3,32) KHWC
    pk = np.asarray(kernel_hwc, dtype=np.uint8).astype(np.uint32)  # byte values in uint32
    tap_ch = pk.reshape(-1, NUM_PES)       # (9, 32) tap-major
    groups = tap_ch.reshape(-1, 4)         # (72, 4)
    words = (groups[:, 3] << 24) | (groups[:, 2] << 16) | (groups[:, 1] << 8) | groups[:, 0]
    return words.astype(np.uint32)


def _run_wsacc_sim(log_file, words, data_i, golden):
    """Write stimulus files and run the verilator WSAcc depthwise TB."""
    with open(os.path.join(sims_dir, 'p9_dw_words.txt'), 'w') as f:
        for wd in words:
            f.write(f'{int(wd):08x}\n')
    with open(os.path.join(sims_dir, 'dw_data_i.txt'), 'w') as f:
        for p in range(NUM_POSITIONS):
            for c in range(NUM_PES):
                for t in range(WINDOW_ELEMENTS):
                    f.write(f'{int(data_i[p, c, t]):02x}\n')
    with open(os.path.join(sims_dir, 'dw_golden.txt'), 'w') as f:
        for p in range(NUM_POSITIONS):
            for c in range(NUM_PES):
                f.write(f'{int(golden[p, c]) & 0xffff:04x}\n')

    verilator_params = [
        '--binary', '--timing', '-j', '4', '-sv',
        '+incdir+../rtl',
        '-Wno-fatal', '-Wno-WIDTHEXPAND', '-Wno-WIDTHTRUNC',
        '-Wno-UNUSEDSIGNAL', '-Wno-UNDRIVEN', '-Wno-UNUSEDPARAM',
        '-Wno-PINMISSING', '-Wno-GENUNNAMED', '-Wno-CASEINCOMPLETE',
        '-Wno-TIMESCALEMOD', '-Wno-IMPLICITSTATIC', '-Wno-LATCH',
        '-Wno-COMBDLY', '-Wno-BLKSEQ', '-Wno-INITIALDLY',
        '-CFLAGS', '-O1',
    ]
    verilator_params_spec = [
        '-GnumPes=32', '-GwindowElements=9', '-GdataWidth=8',
        '-GoutputWidth=16', '-GweightInterfaceWidth=32',
    ]

    compile_command = [
        'verilator', rtl_files[0], rtl_files[1], tb_file,
    ] + verilator_params + verilator_params_spec + [
        '--top-module', top_name, '-o', top_name,
        '--Mdir', f'obj_dir_{top_name}',
    ]

    with open(log_file, 'w+') as f:
        proc = subprocess.Popen(compile_command, shell=False, cwd=sims_dir,
                                stdout=f, stderr=subprocess.STDOUT)
    proc.wait()
    retval = proc.returncode
    assert retval == 0, f'Verilator compilation failed; see {log_file}'

    run_command = [f'./obj_dir_{top_name}/{top_name}']
    with open(log_file, 'a') as f:
        f.write('\n===== VERILATOR RUN COMMAND =====\n')
        f.write(' '.join(run_command))
        f.write('\n')
    sim = subprocess.Popen(run_command, shell=False, cwd=sims_dir,
                           stdout=open(log_file, 'a'), stderr=subprocess.STDOUT)
    sim.wait()
    retval = sim.returncode
    with open(log_file, 'r') as f:
        output = f.read()
    print(output)
    assert retval == 0, f'Simulation failed; see {log_file}'
    assert 'TB_PASS' in output, f'TB_PASS not found in output:\n{output}'
    return output


def test_wsacc_dw32_onnx():
    """WSAcc depthwise check with golden computed from the ONNX weights.

    Loads the mnode1 depthwise weight W (onnx::Conv_543_quantized, (32,1,3,3)),
    builds the real 4-channel-per-word weight words (fixed compile path, P10-DW),
    feeds the same uint8 ifmap windows the existing TB uses, and compares each
    PE's data_o to the ONNX-derived golden sum over taps of
    W[c,0,t//3,t%3] * x[c,p,t]. All 32 PEs at all 4 positions must match.
    """
    os.makedirs(sims_dir, exist_ok=True)
    log_file = os.path.join(sims_dir, 'tb_wsacc_dw32_onnx.log')

    model = onnx.load(onnx_path)
    init = _find_mnode1_weight(model)
    assert init is not None, 'mnode 1 weight initializer Conv_543_quantized not found'
    assert list(init.dims) == [32, 1, 3, 3], list(init.dims)
    w = onnx.numpy_helper.to_array(init).astype(np.int8)  # (32,1,3,3)
    assert w.shape == (32, 1, 3, 3), w.shape

    # Real weight words from the fixed code path (4 channels per word).
    words = _pack_depthwise_words_correct(w)
    assert len(words) == 9 * 8, len(words)

    # Same unsigned uint8 activations the TB already uses (values 0..25 keep
    # |sum| <= 9*128*25 = 28800 < 32767, so the 16-bit signed accumulator
    # cannot wrap and golden is bit-exact vs the RTL's signed data_o).
    rng = np.random.default_rng(1234)
    ifmap = rng.integers(0, 26, size=(1, 5, 5, NUM_PES)).astype(np.uint8)  # NHWC
    padded = np.pad(ifmap, ((0, 0), (1, 1), (1, 1), (0, 0)), mode='constant', constant_values=0)
    positions = [(0, 0), (1, 1), (3, 3), (4, 4)]  # (oh, ow)

    data_i = np.zeros((NUM_POSITIONS, NUM_PES, WINDOW_ELEMENTS), dtype=np.uint8)
    golden = np.zeros((NUM_POSITIONS, NUM_PES), dtype=np.int32)
    nonzero_pes = 0
    for p, (oh, ow) in enumerate(positions):
        for c in range(NUM_PES):
            for t in range(WINDOW_ELEMENTS):
                kh, kw = t // 3, t % 3
                data_i[p, c, t] = padded[0, oh + kh, ow + kw, c]
                golden[p, c] += int(w[c, 0, kh, kw]) * int(data_i[p, c, t])
            if golden[p, c] != 0:
                nonzero_pes += 1
    print(f'P10-DW: nonzero-PE count (all positions) = {nonzero_pes}')

    _run_wsacc_sim(log_file, words, data_i, golden)
