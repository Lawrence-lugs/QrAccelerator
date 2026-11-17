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

    if run:
        with open(log_file, 'w+') as f:
            proc = subprocess.Popen(
                compile_command,
                shell=False,
                cwd='./sims',
                stdout=f,
                stderr=subprocess.STDOUT,
            )
        retval = proc.wait()
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


def qlinearconv_pre_scale_mac(
    mapped_node,
    input_tensor,
    adc_bits: int = 4,
    weight_bits: int = 8,
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

    The weight reordering (``kernel.transpose(0, 3, 1, 2).reshape(O, -1).T``)
    and the ``channel_minor=True`` toeplitz layout are confirmed to make
    ``toeplitz @ w`` reproduce the convolution exactly.  ``channel_minor``
    toeplitz columns are ordered ``(kw, C, kh)`` with ``kh`` fastest, so the
    kernel must be permuted as ``(O, kw, C, kh)`` before flattening.  The
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
        ADC precision used for optional saturation. 4 = RTL reference target
        (saturates to [-8, 7]). 32 (or large) disables saturation for an
        exact integer match.
    weight_bits : int
        Weight precision B in {1, 2, 4, 8}.  Planes b >= B are zero.

    Returns
    -------
    np.ndarray, shape (H*W, O), dtype int64
        Pre-scaling MAC values.
    """
    kernel = mapped_node.kernel  # (O, I, kh, kw), int8
    O, I, kh, kw = kernel.shape
    x_zp = int(mapped_node.x_zp)

    # Reorder weights into toeplitz column order: (kernel_elems, O).
    # channel_minor toeplitz columns are laid out as (kw, C, kh) with kh
    # fastest (confirmed against compute.toeplitzize_input).  transpose(0,3,1,2)
    # -> (O, kw, C, kh); flatten C-order gives (kw, C, kh) with kh inner.
    weights_toeplitz = (
        kernel.transpose(0, 3, 1, 2).reshape(O, -1).T
    ).astype(np.int64)

    # Bit planes: (8, kernel_elems, O). Plane b = (w >> b) & 1 for b < B.
    planes = q.weight_bit_planes(weights_toeplitz, weight_bits, signed=True)

    # Activation toeplitz matrix: (H*W, kernel_elems), padded with x_zp.
    toeplitz = compute.toeplitzize_input(
        in_tensor=input_tensor.squeeze(0),
        kernel_shape=kernel.shape,
        strides=mapped_node.strides,
        pads=mapped_node.pads,
        zero_point=x_zp,
        channel_minor=True,
    )
    toeplitz_i = toeplitz.astype(np.int64)

    # Per-plane dot products: (H*W, O) each.
    per_plane_dot = [
        toeplitz_i @ planes[b].astype(np.int64) for b in range(8)
    ]

    # Combine via shift-add with MSB plane negated (two's complement).
    # B == 1 is the raw dot product (no sign bit to negate separately).
    if weight_bits == 1:
        golden = toeplitz_i @ planes[0].astype(np.int64)
    else:
        golden = sum(
            per_plane_dot[b] << b for b in range(weight_bits - 1)
        ) - (per_plane_dot[weight_bits - 1] << (weight_bits - 1))

    # Zero-point folding: match ONNX QLinearConv pre-output-scale / zp.
    # MUST use the same B-bit-reduced weights as the MAC above (not the raw
    # int8 kernel), otherwise the padded-position contribution and the MAC
    # use inconsistent weights for B < 8.
    w_B = q.quantize_int8_to_bits(kernel, weight_bits, signed=True)
    kernel_sum = w_B.sum(axis=(1, 2, 3)).astype(np.int64)  # (O,)
    golden = golden - (x_zp * kernel_sum)[None, :]

    # Optional ADC saturation (RTL 4-bit ADC saturates to [-8, 7]).
    if adc_bits is not None and adc_bits < 32:
        lo = -(1 << (adc_bits - 1))
        hi = (1 << (adc_bits - 1)) - 1
        golden = np.clip(golden, lo, hi)

    return golden.astype(np.int64)


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

