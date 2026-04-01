"""Shared utilities for QrAccelerator RTL simulation tests.

Provides simulator argument definitions, the `run_simulation()` driver for
VCS / Xcelium / Verilator, and helper functions for result comparison (RMSE/SNR),
parameter file generation, and plot output.
"""

import subprocess
import os
import sys
import shutil
import marp.quantization.quant as q
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import pytest
sns.set_theme()
from marp.compile.stimulus_gen import *
from marp.compile.compile import *

sim_args = {'vcs':  [
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
                '+access+r'
            ],
            'verilator': [
                '--binary',
                '--timing',
                '-j', '0',
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

def empty_directory(directory):
    """
    Empty the directory if it exists.
    """
    if os.path.exists(directory):
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
        run_command = [f'./obj_dir_{top_name}/V{top_name}']

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
    with open(log_file, 'r') as f:
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
    with open(log_file,'r') as f:
        lines = f.readlines()[-nlines:]
        a = ''.join(lines)
    return '\n'.join([m,a])

def get_log(log_file):
    with open(log_file,'r') as f:
        print(f.read())

def rmse_snr(expected, actual):
    """Return (RMSE, SNR in dB) between *expected* and *actual* arrays."""
    rmse = np.sqrt(np.mean((expected - actual)**2))
    snr = 10*np.log10(np.var(expected)/np.var(expected - actual))
    print(f'RMSE:{rmse}, SNR:{snr}')
    return rmse, snr

def save_scatter_fig(expected, actual, title, filename):
    """Save an expected-vs-actual scatter plot to ``images/png/<filename>.png``."""
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
 
def plot_diff_channels(diff, tensor_format='NCHW', filename='diff_channels', bitPrecision=8, save=True):
    """
    Plots all channels of the diff tensor in a subplot grid.

    Parameters:
    - diff: numpy.ndarray, the tensor to plot
    - tensor_format: str, format of the tensor ('NCHW' or 'NHWC')
    - bitPrecision: int, bit precision for value range (default 8)
    """
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
