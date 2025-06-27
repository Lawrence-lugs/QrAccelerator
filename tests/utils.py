import subprocess
import os
import sys
import hwacctools.quantization.quant as q
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import pytest
sns.set_theme()
from tests.stim_lib.stimulus_gen import *
from tests.stim_lib.compile import *

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
    
    print('=====VCS COMMAND=====')
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
        # get_log(log_file)

def write_parameter_definition_file(parameter_list,filepath):
    with open(filepath,'w') as f:
        f.write(f'`ifndef PARAMETERS_FILE\n')
        f.write(f'`define PARAMETERS_FILE\n')
        f.write(f'`define PYTEST_GENERATED_PARAMS\n')
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
    rmse = np.sqrt(np.mean((expected - actual)**2))
    snr = 10*np.log10(np.var(expected)/np.var(expected - actual))
    print(f'RMSE:{rmse}, SNR:{snr}')
    return rmse, snr

def save_scatter_fig(expected, actual, title, filename):
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
