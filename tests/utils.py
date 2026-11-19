"""Shared utilities for QrAccelerator RTL simulation tests.

Provides simulator argument definitions, the `run_simulation()` driver for
VCS / Xcelium / Verilator, and helper functions for result comparison (RMSE/SNR),
parameter file generation, and plot output.
"""

import subprocess
import os
import sys
import shutil
import qracc_marp.quantization.quant as q
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
try:
    import seaborn as sns
except ImportError:
    sns = None
import pytest
if sns is not None:
    sns.set_theme()
from qracc_marp.compile import compute
from qracc_marp.compile.stimulus_gen import *
from qracc_marp.compile.compile import *

sim_args = {'vcs':  [
                '+define+QRACC_PARAMS_FILE="qracc_params.svh"',
                '-full64',
                '-debug_pp',
                '-debug_access',
                '-sverilog',
                '+neg_tchk',
                '-l', 'vcs.log',
                '-R', '+lint=TFIPC-L',
                '+define+SYNOPSYS',
                '+incdir+../rtl',
            ],
            'xrun': [
                '+define+QRACC_PARAMS_FILE="qracc_params.svh"',
                '+access+r'
            ],
            'verilator': [
                '+define+QRACC_PARAMS_FILE="qracc_params.svh"',
                '--binary',
                '--timing',
                '-j', '1',
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
}

# QRACC_DEBUG must be set in the environment BEFORE this module is imported.
# It is checked at import time (below) to decide whether '+define+DEBUG' is
# appended to sim_args['verilator']. Setting it after import is too late;
# callers must then append '+define+DEBUG' to sim_args['verilator'] explicitly.
if os.environ.get('QRACC_DEBUG') == '1':
    sim_args['verilator'].append('+define+DEBUG')

# Runtime plusargs forwarded to the verilator simulation binary.
# Populated by individual tests (diagnostic hooks); empty by default so
# default runs are unchanged.  Verilator rejects `+cap_file=...` at compile
# time, so these must be appended to the runtime binary command.
VERILATOR_RUN_PLUSARGS: list[str] = []

def empty_directory(directory):
    """
    Empty the directory, creating it if necessary.
    """
    os.makedirs(directory, exist_ok=True)
    for filename in os.listdir(directory):
            file_path = os.path.join(directory, filename)
            try:
                if os.path.isfile(file_path) or os.path.islink(file_path):
                    os.unlink(file_path)
                elif os.path.isdir(file_path):
                    os.rmdir(file_path)
            except Exception as e:
                print(f'Failed to delete {file_path}. Reason: {e}')

def run_simulation(simulator,parameter_list,package_list,tb_file,sim_args,rtl_file_list,log_file,run=True,top_module=None):
    """Compile and run an RTL simulation, then assert TEST SUCCESS in the log.

    Parameters
    ----------
    simulator : str
        One of 'vcs', 'xrun', or 'verilator'.
    parameter_list : list[str] | dict
        Design parameters.  Lists use 'NAME=VALUE' strings; dicts map name->value.
    package_list : list[str]
        SystemVerilog package files to compile first.
    tb_file : str
        Path to the testbench source file (relative to ``sims/``).
    sim_args : dict
        Mapping of simulator name to its argument list.
    rtl_file_list : list[str]
        RTL source files to compile.
    log_file : str
        Path to write simulation stdout.
    run : bool
        If False, only build the command without executing.
    top_module : str | None
        Explicit top-module name; inferred from *tb_file* when None.
    """
    os.makedirs('./sims', exist_ok=True)

    if shutil.which(simulator) is None:
        pytest.skip(f"{simulator} not found on PATH (install {simulator} or run inside the devcontainer)")

    if simulator == 'verilator':
        _run_verilator_simulation(parameter_list, package_list, tb_file, sim_args, rtl_file_list, log_file, run, top_module)
        return

    if simulator == 'vcs':
        parameter_list = [f'-pvalue+{tb_file}.'+p for p in parameter_list]
    else:
        parameter_list = []

    top_command = ['-top',top_module] if top_module else []

    command = [
            simulator,
            *package_list,
            tb_file
        ] + sim_args[simulator] + rtl_file_list + parameter_list + top_command
    
    print(f'====={simulator.upper()} COMMAND=====')
    print(' '.join(command))
    print('=====LOG FILE========')
    print(log_file)
    print('=====================')

    
    if run:
        with open(log_file,'w+') as f:
            sim = subprocess.Popen(
            command, 
            shell=False,
            cwd='./sims',
            stdout=f
            )
        retval = sim.wait()
        if retval:
            get_log(log_file)
        assert not retval, get_log_tail(log_file,10)

    # Read log file
    with open(log_file,'r+') as f:
        f.seek(0)
        out = [line for line in f.readlines()]
        assert 'TEST SUCCESS\n' in out, get_log_tail(log_file,10)


def _run_verilator_simulation(parameter_list, package_list, tb_file, sim_args_dict, rtl_file_list, log_file, run=True, top_module=None):
    """Run a Verilator simulation using its two-step compile-then-run flow."""

    # Verilator parameters use -G syntax
    if isinstance(parameter_list, dict):
        verilator_params = [f'-G{name}={value}' for name, value in parameter_list.items()]
    elif isinstance(parameter_list, list):
        verilator_params = [f'-G{p}' for p in parameter_list] if parameter_list else []
    else:
        verilator_params = []

    # Determine top module name
    if top_module:
        top_name = top_module
    else:
        # Extract module name from tb_file path
        top_name = os.path.splitext(os.path.basename(tb_file))[0]

    top_command = ['--top-module', top_name]

    # Step 1: Compile
    compile_command = [
        'verilator',
        *package_list,
        tb_file,
    ] + sim_args_dict['verilator'] + rtl_file_list + verilator_params + top_command + [
        '-o', f'V{top_name}',
        '--Mdir', f'obj_dir_{top_name}',
    ]

    print('=====VERILATOR COMPILE COMMAND=====')
    print(' '.join(compile_command))
    print('=====LOG FILE========')
    print(log_file)
    print('===================================')

    # Build in parallel first (much faster); some verilator/plugin combinations
    # intermittently fail under -j 0, so fall back to the configured serial
    # build (-j 1) if the parallel attempt does not succeed.
    parallel_command = list(compile_command)
    for idx, arg in enumerate(parallel_command):
        if arg == '-j' and idx + 1 < len(parallel_command):
            parallel_command[idx + 1] = '0'
            break

    def _run_compile(cmd):
        with open(log_file, 'w+') as f:
            proc = subprocess.Popen(
                cmd,
                shell=False,
                cwd='./sims',
                stdout=f,
                stderr=subprocess.STDOUT,
            )
        return proc.wait()

    if run:
        retval = _run_compile(parallel_command)
        if retval:
            print('Parallel verilator build failed; retrying with the serial '
                  '(-j 1) configuration.')
            retval = _run_compile(compile_command)
        if retval:
            get_log(log_file)
        assert not retval, f'Verilator compilation failed:\n{get_log_tail(log_file, 30)}'

        # Step 2: Run the compiled binary
        run_command = [f'./obj_dir_{top_name}/V{top_name}', *VERILATOR_RUN_PLUSARGS]

        print('=====VERILATOR RUN COMMAND=====')
        print(' '.join(run_command))
        print('===============================')

        with open(log_file, 'a') as f:
            f.write('\n===== SIMULATION OUTPUT =====\n')
            sim = subprocess.Popen(
                run_command,
                shell=False,
                cwd='./sims',
                stdout=f,
                stderr=subprocess.STDOUT,
            )
        retval = sim.wait()
        # Verilator returns 0 on $finish, but some testbenches call $finish after failure
        # We check for TEST SUCCESS in the log instead of relying on return code

    # Read log file and check for success
    with open(log_file, 'r', errors='replace') as f:
        out = [line for line in f.readlines()]
        assert 'TEST SUCCESS\n' in out, get_log_tail(log_file, 10)

def write_parameter_definition_file(parameter_list,filepath):
    with open(filepath,'w') as f:
        f.write(f'`ifndef PARAMETERS_FILE\n')
        f.write(f'`define PARAMETERS_FILE\n')
        f.write(f'`define PYTEST_GENERATED_PARAMS\n')
        for name, value in parameter_list.items():
            f.write(f'`define {name} {value}\n')    
        f.write(f'`endif // PARAMETERS_FILE\n')


def get_log_tail(log_file,nlines):
    m = f'See {log_file} for details\n' 
    with open(log_file,'r', errors='replace') as f:
        lines = f.readlines()[-nlines:]
        a = ''.join(lines)
    return '\n'.join([m,a])

def get_log(log_file):
    with open(log_file,'r', errors='replace') as f:
        print(f.read())

def rmse_snr(expected, actual):
    """Return (RMSE, SNR in dB) between *expected* and *actual* arrays."""
    rmse = np.sqrt(np.mean((expected - actual)**2))
    snr = 10*np.log10(np.var(expected)/np.var(expected - actual))
    print(f'RMSE:{rmse}, SNR:{snr}')
    return rmse, snr


def qlinearconv_onnx_reference(
    mapped_node,
    input_tensor,
    nx_model,
    weight_bits: int = 8,
    weight_signed: bool = None,
) -> np.ndarray:
    """Real ONNX Runtime output for one QLinearConv node on one input.

    This is the only reference in the test-suite that actually executes ONNX.
    It runs the target node with ``input_tensor`` as the node input, so it can
    be compared with the RTL for the exact same activation data.

    For ``weight_bits < 8`` the weight initializer is replaced by the B-bit
    signed values ``q = w >> (8-B)`` and the node's ``w_scale`` initializer is
    multiplied by ``2**(8-B)``.  That represents the same real weights the
    hardware uses: the hardware MAC consumes ``q`` directly and the compiler
    restores the factor in the output scale.

    ``weight_bits=1, weight_signed=False`` is the legacy binary model: its
    weights are already 0/1 and its ``w_scale`` already corresponds to them,
    so the model is used unchanged.

    Returns the node output in NHWC order ``(H, W, O)`` to match the RTL
    ``hw_ofmap`` layout.
    """
    import copy

    import onnx
    from qracc_marp.onnx_tools import onnx_utils

    if weight_signed is None:
        weight_signed = weight_bits > 1

    model = copy.deepcopy(nx_model)
    # A B=1 unsigned model (the legacy binary model) already carries 0/1
    # weights and its own w_scale; leave both untouched.
    binary_model = weight_bits == 1 and not weight_signed
    if not binary_model:
        wname = mapped_node.nx_node.input[3]
        init = next(i for i in model.graph.initializer if i.name == wname)
        w = onnx.numpy_helper.to_array(init)
        q_w = q.quantize_int8_to_bits(
            w, weight_bits, signed=weight_signed).astype(np.int8)
        for idx, old in enumerate(model.graph.initializer):
            if old.name == wname:
                model.graph.initializer[idx].CopyFrom(
                    onnx.numpy_helper.from_array(q_w, name=wname))
                break

        if weight_bits < 8:
            wscale_name = mapped_node.nx_node.input[4]
            for idx, old in enumerate(model.graph.initializer):
                if old.name == wscale_name:
                    ws = onnx.numpy_helper.to_array(old).astype(np.float32)
                    model.graph.initializer[idx].CopyFrom(
                        onnx.numpy_helper.from_array(
                            ws * (2 ** (8 - weight_bits)), name=wscale_name))
                    break

    out = onnx_utils.get_intermediate_tensor_value(
        model,
        mapped_node.nx_node.output[0],
        input_dict={mapped_node.nx_node.input[0]: input_tensor},
    )
    if out.ndim == 4:
        return np.transpose(out, (0, 2, 3, 1))
    if out.ndim == 1:
        # QLinearMatMul on a pooled vector: NHWC with H=W=1.
        return out.reshape(1, 1, 1, -1)
    if out.ndim == 2:
        return out.reshape(1, 1, *out.shape)
    return out


def qlinearconv_pre_scale_mac(
    mapped_node,
    input_tensor,
    adc_bits: int = 32,
    weight_bits: int = 8,
    adc_mode: str = "output",
    adc_shift: int = 0,
    unfold: bool = False,
    fs_counts: float = None,
    ladder: str = "bipolar",
    weight_signed: bool = None,
) -> np.ndarray:
    """Compute the pre-scaling MAC golden array for a QLinearConv node.

    Returns an ``(H*W, O)`` int64 array of pre-scaling MAC values (one per
    output pixel / output channel), matching the ONNX QLinearConv
    pre-output-scale / zero-point result::

        golden = toeplitz @ w_B  -  x_zp * sum(kernel per output channel)

    where ``w_B`` is the B-bit-reduced weight matrix reordered into toeplitz
    column order and combined via bit-plane shift-add (MSB plane negated,
    i.e. two's complement).  This mirrors ``rtl/seq_acc.sv``: per-plane MACs
    are combined by the shift-add tree with the MSB plane sign-corrected by
    ``twos_to_bipolar``.

    This function is a numpy reconstruction, **not** an ONNX Runtime call.
    Use :func:`qlinearconv_onnx_reference` for the actual ONNX output.

    The weight reordering (``kernel.transpose(0, 2, 3, 1).reshape(O, -1).T``)
    and the ``channel_minor=False`` toeplitz layout are confirmed to make
    ``toeplitz @ w`` reproduce the convolution exactly.  ``channel_minor=False``
    toeplitz columns are ordered ``(kh, kw, C)`` with the channel fastest, so
    the kernel is permuted as ``(O, kh, kw, C)`` before flattening.  The
    toeplitz matrix is padded with ``mapped_node.x_zp``, matching the RTL's
    padding value, so the subsequent ``- x_zp * sum(kernel)`` zero-point fold
    yields exactly ONNX QLinearConv pre-output-scale/zp:
    ``sum_e (X_pad[e] - x_zp) * W[e]`` is zero in the padded positions.

    Parameters
    ----------
    mapped_node : qracc_marp.mapping.core.MappedNode
        Mapped ONNX QLinearConv node (exposes ``kernel``, ``x_zp``,
        ``pads``, ``strides``).
    input_tensor : np.ndarray
        uint8 NCHW array (batch=1), same as the RTL testbench uses.
    adc_bits : int
        ADC comparator count.  For ``adc_mode="per_plane"`` it is the flash-ADC
        width used for every partial sum (4 in the RTL).  For
        ``adc_mode="output"`` it is the width of the legacy final clip (4
        saturates to [-8, 7]); 32 disables clipping.  Ignored by
        ``adc_mode="none"``.
    weight_bits : int
        Weight precision B in {1, 2, 4, 8}.  Planes b >= B are zero.
    adc_mode : {"none", "output", "per_plane", "per_plane_legacy"}
        ``"none"`` returns the exact integer MAC.  ``"output"`` is the legacy
        behaviour: the *final* folded MAC is clipped to ``adc_bits`` bits (this
        is not what the hardware does; see the ablation test).  ``"per_plane"``
        emulates ``rtl/ts_qracc.sv`` with a *fixed* full-scale flash ADC:
        every ``(activation bit j, weight plane b)`` partial sum is quantised
        before the shift-add, and ``adc_shift`` *halves the span toward
        ``V_RST``* (finer LSB, earlier saturation).  ``"per_plane_legacy"``
        keeps the pre-2026-11-18 inverted convention where ``adc_shift``
        widened the window and coarsened the LSB.
    adc_shift : int
        ``cfg.adc_ref_range_shifts`` (``s``) used by the ``per_plane`` modes.
    fs_counts : float, optional
        Half-span in switch-matrix counts at ``s == 0`` (per-layer analog full
        scale).  ``None`` derives it from the largest ``|mbl_value|`` of this
        node, which is what the compiler-side chooser does.
    ladder : {"bipolar", "binary"}
        Switch-matrix arrangement.  ``"bipolar"`` gives
        ``mbl = 2P - A_j`` (``A_j`` = active lanes for activation bit ``j``)
        and the returned MAC undoes the resulting bias; ``"binary"`` uses the
        unipolar ``mbl = P``.
    unfold : bool
        When True, do not subtract ``x_zp * sum(w_B)``.  The RTL pre-shift
        accumulator must be compared against the unfolded value because the
        zero-point fold is folded into ``mapped_node.biases`` and applied by
        ``output_scaler`` instead.
    weight_signed : bool, optional
        Signed B-bit weight planes.  Defaults to ``weight_bits > 1``: the
        B=1 binary path uses 0/1 weights, while B>1 uses two's complement.

    Returns
    -------
    np.ndarray, shape (H*W, O), dtype int64
        Pre-scaling MAC values.
    """
    if adc_mode not in ("none", "output", "per_plane", "per_plane_legacy"):
        raise ValueError(
            f"adc_mode must be 'none', 'output', 'per_plane' or "
            f"'per_plane_legacy', got {adc_mode!r}"
        )
    if weight_signed is None:
        # B=1 binary weights are 0/1 in the hardware and in the binary ONNX
        # model; B>1 uses signed two's-complement planes.
        weight_signed = weight_bits > 1
    kernel = mapped_node.kernel  # (O, I, kh, kw), int8
    O, I, kh, kw = kernel.shape
    x_zp = int(mapped_node.x_zp)

    # QLinearMatMul is mapped as a 1x1 conv; its intermediate input arrives as
    # a bare vector, not NCHW.  Treat it as C x 1 x 1.
    if input_tensor.ndim == 1:
        input_tensor = input_tensor.reshape(1, -1, 1, 1)

    # The hardware toeplitz is the raw receptive field flattened as
    # (kh, kw, C) with C fastest (channel_minor=False).  Verified against the
    # RTL activation capture: the 27 lane values match this order exactly.
    weights_toeplitz = (
        kernel.transpose(0, 2, 3, 1).reshape(O, -1).T
    ).astype(np.int64)

    # Bit planes: (8, kernel_elems, O). Plane b = (w >> b) & 1 for b < B.
    planes = q.weight_bit_planes(weights_toeplitz, weight_bits,
                                 signed=weight_signed)

    # Activation toeplitz matrix: (H*W, kernel_elems), padded with x_zp.
    toeplitz = compute.toeplitzize_input(
        in_tensor=input_tensor.squeeze(0),
        kernel_shape=kernel.shape,
        strides=mapped_node.strides,
        pads=mapped_node.pads,
        zero_point=x_zp,
        channel_minor=False,
    )
    toeplitz_i = toeplitz.astype(np.int64)

    # Per-plane dot products: (H*W, O) each.
    per_plane_dot = [
        toeplitz_i @ planes[b].astype(np.int64) for b in range(8)
    ]

    # Exact integer MAC: shift-add with MSB plane negated (two's complement).
    # B == 1 is the raw dot product (no sign bit to negate separately).
    if weight_bits == 1:
        mac = toeplitz_i @ planes[0].astype(np.int64)
    else:
        mac = sum(
            per_plane_dot[b] << b for b in range(weight_bits - 1)
        ) - (per_plane_dot[weight_bits - 1] << (weight_bits - 1))

    if adc_mode in ("per_plane", "per_plane_legacy"):
        # Bit-serial, per-plane emulation of seq_acc + ts_qracc.  The flash ADC
        # quantises *each* (activation bit j, weight plane b) partial sum, so
        # the range shift trades comparator range against resolution.
        #
        # "per_plane"        fixed full scale, `adc_shift` zooms toward V_RST,
        #                    bipolar or binary ladder (see
        #                    PLAN_adc_range_model_correction.md).
        # "per_plane_legacy" inverted shift semantics, kept for old captures.
        rows = mac.shape[0]
        mbl = {}
        act_counts = np.zeros((rows,), dtype=np.int64)
        for j in range(8):  # PISO bit index, LSB first (input_bits=9 -> 8)
            xj = (toeplitz_i >> j) & 1
            a_j = xj.sum(axis=1).astype(np.int64)
            act_counts += a_j << j
            for b in range(weight_bits):
                partial = xj @ planes[b].astype(np.int64)
                if adc_mode == "per_plane" and ladder == "bipolar":
                    # Bipolar switch matrix: mbl = 2P - A_j (A_j = active lanes).
                    mbl[(j, b)] = 2 * partial - a_j[:, None]
                else:
                    mbl[(j, b)] = partial
        if adc_mode == "per_plane":
            if fs_counts is None:
                fs_counts = float(max(int(np.abs(m).max()) for m in mbl.values()))
            codes = {
                key: q.adc_quantize(m, adc_bits=adc_bits, shift=adc_shift,
                                    fs_counts=fs_counts, mode=ladder)
                for key, m in mbl.items()
            }
        else:
            codes = {
                key: q.adc_quantize_legacy(m, adc_bits=adc_bits, shift=adc_shift)
                for key, m in mbl.items()
            }
        acc = np.zeros_like(mac)
        for j in range(8):
            tree = np.zeros_like(mac)
            for b in range(weight_bits):
                term = codes[(j, b)] << b
                # RTL negates the MSB plane.  B == 1 signed is excluded: the
                # hardware negates its only plane, which does not match the
                # ONNX signed quantisation used here.
                if b == weight_bits - 1 and weight_bits > 1:
                    term = -term
                tree += term
            acc += tree << j
        if adc_mode == "per_plane":
            lsb = float(fs_counts) / float(1 << (adc_bits - 1 + adc_shift))
            mac = acc.astype(np.float64) * lsb
            if ladder == "bipolar":
                # Sum_b sign_b*2**b == -1, so the mbl bias A_j contributes -A_j
                # to the tree; undo it and halve (the RTL result is 2*MAC).
                mac = (mac - act_counts[:, None]) / 2.0
            mac = np.rint(mac).astype(np.int64)
        else:
            mac = acc

    # Zero-point folding: match ONNX QLinearConv pre-output-scale / zp.
    # MUST use the same B-bit-reduced weights as the MAC above (not the raw
    # int8 kernel), otherwise the padded-position contribution and the MAC
    # use inconsistent weights for B < 8.
    w_B = q.quantize_int8_to_bits(kernel, weight_bits, signed=weight_signed)
    kernel_sum = w_B.sum(axis=(1, 2, 3)).astype(np.int64)  # (O,)
    if not unfold:
        mac = mac - (x_zp * kernel_sum)[None, :]

    # Legacy behaviour: quantise the *final* (folded) MAC as a narrow signed
    # value.  This is NOT what the hardware does and is kept only so the
    # ablation test can quantify why it is wrong.
    if adc_mode == "output" and adc_bits is not None and adc_bits < 32:
        lo = -(1 << (adc_bits - 1))
        hi = (1 << (adc_bits - 1)) - 1
        mac = np.clip(mac, lo, hi)

    return mac.astype(np.int64)


def qlinearconv_post_scale_mac(
    mapped_node,
    input_tensor,
    weight_bits: int = 8,
    adc_mode: str = "none",
    adc_shift: int = 0,
    fs_counts: float = None,
    ladder: str = "bipolar",
    weight_signed: bool = None,
) -> np.ndarray:
    """Full Python golden for the post-scaler int8 output.

    Models the actual datapath contract:

    * B>1: the hardware consumes ``q = w >> (8-B)`` (signed B-bit weights),
      ``seq_acc`` publishes ``2*MAC``, and the compiler sets
      ``output_scale = mapped_node.scale * 2**(8-B) / 2`` and
      ``output_bias = 2 * (bias_raw - x_zp*sum(q))``;
    * B=1: the binary path uses 0/1 weights, publishes MAC (no 2x), and uses
      ``output_scale = mapped_node.scale`` and
      ``output_bias = bias_raw - x_zp*sum(q)``;
    * the scaler applies ``(post + output_bias) * output_scale + y_zp``.

    This is the Python counterpart of ``output_scaler``.  With
    ``adc_mode="none"`` it should agree with :func:`qlinearconv_onnx_reference`
    to within fixed-point rounding; with ``"per_plane"`` it includes the flash
    ADC approximation.

    Returns NHWC ``(H, W, O)``, clipped to int8 range.
    """
    if weight_signed is None:
        weight_signed = weight_bits > 1

    if mapped_node.depthwise:
        # WSAcc uses the raw int8 depthwise kernel, not B-bit planes, and
        # publishes MAC (no 2x).  Build the per-channel MAC directly.
        kernel = mapped_node.kernel  # (O, 1, kh, kw)
        O, _, kh, kw = kernel.shape
        x = input_tensor.squeeze(0)
        # Output size comes from the same toeplitz helper, not the input size.
        mac = None
        rows = None
        for o in range(O):
            toe = compute.toeplitzize_input(
                x[o:o + 1],
                kernel_shape=(1, 1, kh, kw),
                strides=mapped_node.strides,
                pads=mapped_node.pads,
                zero_point=int(mapped_node.x_zp),
                channel_minor=False,
            )
            if rows is None:
                rows = toe.shape[0]
                mac = np.zeros((rows, O), dtype=np.int64)
            mac[:, o] = toe.astype(np.int64) @ kernel[o].reshape(-1).astype(np.int64)
        bias_out = np.asarray(mapped_node.biases, dtype=np.int64)
        scale = np.asarray(mapped_node.scale, dtype=np.float64)
        y = (mac + bias_out[None, :]) * scale[None, :] + int(mapped_node.y_zp)
        y = np.clip(np.rint(y), 0, 255)
        H = W = int(round(np.sqrt(rows)))
        assert H * W == rows, (
            f'cannot reshape {rows} windows to HxW; expected square')
        return y.reshape(H, W, O).astype(np.uint8)

    mac = qlinearconv_pre_scale_mac(
        mapped_node,
        input_tensor,
        adc_bits=4 if adc_mode == "per_plane" else 32,
        weight_bits=weight_bits,
        adc_mode=adc_mode,
        adc_shift=adc_shift,
        unfold=True,
        fs_counts=fs_counts,
        ladder=ladder,
        weight_signed=weight_signed,
    )

    w_B = q.quantize_int8_to_bits(
        mapped_node.kernel, weight_bits,
        signed=weight_signed).astype(np.int64)
    raw_bias = (np.asarray(mapped_node.biases, dtype=np.int64)
                + int(mapped_node.x_zp)
                * mapped_node.kernel.sum(axis=(1, 2, 3), dtype=np.int64))
    bias_B = raw_bias - int(mapped_node.x_zp) * w_B.sum(
        axis=(1, 2, 3), dtype=np.int64)

    scale = np.asarray(mapped_node.scale, dtype=np.float64)
    # seq_acc shifts the published MAC by adc_ref_range_shifts (s).  The
    # scaler must divide by 2**s and the post-shift bias must be pre-shifted.
    s = int(adc_shift)
    if weight_bits == 1:
        post = mac
        bias_out = bias_B * (2 ** s)
        scale = scale / (2 ** s)
    else:
        post = 2 * mac
        bias_out = 2 * bias_B * (2 ** s)
        scale = scale * 0.5 * (2 ** (8 - weight_bits)) / (2 ** s)
    y = (post + bias_out[None, :]) * scale[None, :] + int(mapped_node.y_zp)
    y = np.clip(np.rint(y), 0, 255)

    O = mapped_node.kernel.shape[0]
    H = W = int(round(np.sqrt(mac.shape[0])))
    assert H * W == mac.shape[0], (
        f'cannot reshape {mac.shape[0]} windows to HxW; expected square')
    return y.reshape(H, W, O).astype(np.uint8)


def qlinearconv_prescale_snr(
    mapped_node,
    input_tensor,
    weight_bits: int = 8,
    adc_shift: int = 0,
    adc_bits: int = 4,
    fs_counts: float = None,
    ladder: str = "bipolar",
) -> dict:
    """Predicted SNR of the RTL per-plane ADC datapath on one conv window set.

    Compares the flash-ADC emulation (``adc_mode="per_plane"``) against the
    exact integer MAC, both **unfolded** (the RTL accumulator is unfolded; the
    zero-point fold lives in ``mapped_node.biases``).  This is the reference the
    RTL measurement must match within the tolerance documented in
    ``tests/test_marp_multibit_prestack.py``.

    ``adc_shift`` is ``cfg.adc_ref_range_shifts`` under the *fixed-full-scale*
    convention (each step halves the span toward ``V_RST``); ``fs_counts`` and
    ``ladder`` are passed through to the emulation.

    Returns a dict with ``exact``, ``model``, ``snr_db``, ``snr_affine_db``,
    ``max_abs_err`` and ``fs_counts``.
    """
    exact = qlinearconv_pre_scale_mac(
        mapped_node, input_tensor, adc_bits=32, weight_bits=weight_bits,
        adc_mode="none", unfold=True,
    )
    model = qlinearconv_pre_scale_mac(
        mapped_node, input_tensor, adc_bits=adc_bits, weight_bits=weight_bits,
        adc_mode="per_plane", adc_shift=adc_shift, unfold=True,
        fs_counts=fs_counts, ladder=ladder,
    )
    err = exact - model
    var_ref = float(np.var(exact.astype(np.float64)))
    var_err = float(np.var(err.astype(np.float64)))
    snr = float("inf") if var_err == 0 else 10.0 * np.log10(var_ref / var_err)

    # SNR after a per-channel gain+offset fit: this is the figure of merit once
    # the output scaler calibration is applied (a global gain/offset error is
    # absorbed by calibration, a genuine quantisation error is not).
    e = exact.astype(np.float64)
    m = model.astype(np.float64)
    fitted = np.empty_like(e)
    for c in range(e.shape[1]):
        A = np.stack([m[:, c], np.ones(e.shape[0])], axis=1)
        coef, *_ = np.linalg.lstsq(A, e[:, c], rcond=None)
        fitted[:, c] = A @ coef
    var_fit = float(np.var(e - fitted))
    snr_aff = float("inf") if var_fit == 0 else 10.0 * np.log10(var_ref / var_fit)
    return {
        "exact": exact,
        "model": model,
        "snr_db": snr,
        "snr_affine_db": snr_aff,
        "max_abs_err": int(np.abs(err).max()) if err.size else 0,
        "fs_counts": fs_counts,
    }


def save_scatter_fig(expected, actual, title, filename, enabled=False):
    """Save an expected-vs-actual scatter plot to ``images/png/<filename>.png``."""
    if not enabled:
        return
    fig, ax = plt.subplots()
    plt.figure(figsize=(4,4))
    ax = sns.scatterplot(
        x=actual.flatten(), 
        y=expected.flatten(),
        size=1,
        legend=False
    )
    ax.set_title(title)
    ax.set_xlabel('Actual')
    ax.set_ylabel('Ideal')
    lim = [expected.min(),expected.max()]
    sns.lineplot(x=lim,y=lim,color='gray',linestyle='--')
    plt.tight_layout()
    # plt.savefig(f'images/{filename}.svg') # Saving scatter plots to SVG is a little too slow
    plt.savefig(f'images/png/{filename}.png')
    plt.close()
 
def plot_diff_channels(diff, tensor_format='NCHW', filename='diff_channels', bitPrecision=8, save=False):
    """
    Plots all channels of the diff tensor in a subplot grid.

    Parameters:
    - diff: numpy.ndarray, the tensor to plot
    - tensor_format: str, format of the tensor ('NCHW' or 'NHWC')
    - bitPrecision: int, bit precision for value range (default 8)
    - save: bool, if False, do not create or save any figure
    """
    if not save:
        return
    diff_2plot = np.abs(diff) 
    if tensor_format == 'NHWC':
        diff_2plot = diff_2plot.transpose(0, 3, 1, 2)  # Convert to NCHW format for plotting

    num_channels = diff_2plot.shape[1]  # Number of channels in the last dimension
    rows = (num_channels + 7) // 8  # Calculate rows for 8 columns
    fig, axs = plt.subplots(rows, 8, figsize=(20, 10+2.5*(rows-4)), dpi=300)
    axs = axs.flatten()  # Flatten the axes array for easier indexing
    vmin, vmax = 0, 2**bitPrecision - 1

    for i in range(num_channels):
        ax = axs[i]
        im = ax.imshow(diff_2plot[0, i], vmin=vmin, vmax=vmax, cmap='CMRmap')
        ax.set_title(f'Channel {i}')
        ax.axis('off')

    # Hide unused subplots
    for j in range(num_channels, len(axs)):
        axs[j].axis('off')

    # Unified colorbar with fixed range
    plt.subplots_adjust(bottom=0.15)  # Make space for colorbar
    cbar = fig.colorbar(im, ax=axs, orientation='horizontal')
    cbar.set_label('Difference Value')
    plt.suptitle('Difference between Python and HW Results', fontsize=16)

    if save:
        plt.savefig(f'images/{filename}.svg', bbox_inches='tight')
        plt.savefig(f'images/png/{filename}.png', bbox_inches='tight')
    plt.close()

