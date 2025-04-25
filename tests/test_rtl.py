
import subprocess
import os
import sys
import hwacctools.quantization.quant as q
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
sns.set_theme()
from tests.stim_lib.stimulus_gen import *

# simulator = 'xrun'
sim_args = {'vcs':  [
                '-full64',
                '-debug_pp',
                '-debug_access',
                '-sverilog',
                '+neg_tchk',
                '-l', 'vcs.log',
                '-R', '+lint=TFIPC-L',
                '+define+SYNOPSYS'
            ],
            'xrun': [
                '+access+r'
            ]
}

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
    
    print(command)
    print(log_file)
    
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
        get_log(log_file)

def write_parameter_definition_file(parameter_list,filepath):
    with open(filepath,'w') as f:
        f.write(f'`define PYTEST_GENERATED_PARAMS\n')
        for name, value in parameter_list.items():
            f.write(f'`define {name} {value}\n')

def test_qr_acc_top(
    col_symmetric,
    simulator,
    seed,
    padding = 1,
    stride = 1,
    ifmap_shape = (1,3,16,16),
    ifmap_bits = 8,
    kernel_shape = (32,3,3,3), # K C H W
    kernel_bits = 1,
    ofmap_bits = 8,
    core_shape = (256,32)
):  
    weight_mode = 'binary'
    mac_mode = 1 if weight_mode == 'binary' else 0
  
    package_list = ['../rtl/qracc_params.svh','../rtl/qracc_pkg.svh']
    rtl_file_list = [ 
        '../rtl/qr_acc_wrapper.sv',
        '../rtl/seq_acc.sv',
        '../rtl/ts_qracc.sv',
        '../rtl/wr_controller.sv',
        '../rtl/twos_to_bipolar.sv',
        '../rtl/qr_acc_top.sv',
        '../rtl/output_scaler/output_scaler_set.sv',
        '../rtl/output_scaler/output_scaler.sv',
        '../rtl/memory/ram_2w2r.sv',
        '../rtl/feature_loader/feature_loader.sv',
        '../rtl/control/qracc_controller.sv'
    ]
    tb_name = 'tb_qracc_top'
    tb_path = 'qracc_top'
    stimulus_output_path = f'tb/{tb_path}/inputs'
    param_file_path = 'rtl/qracc_params.svh'

    # Setup log paths
    tb_file = f'../tb/{tb_path}/{tb_name}.sv'
    log_file = f'tests/logs/{tb_name}_{simulator}.log'
    logdir = os.path.dirname(log_file)
    os.makedirs(logdir,exist_ok=True)

    # Pre-simulation
    stimulus = generate_top_inputs(stimulus_output_path,stride,ifmap_shape,ifmap_bits,kernel_shape,kernel_bits,core_shape)
    
    ifmap_shape_with_padding = (ifmap_shape[0],ifmap_shape[1],ifmap_shape[2]+2*padding,ifmap_shape[3]+2*padding)

    ofmap_dimx = ((ifmap_shape[2] - kernel_shape[2] + 2*padding) // stride) + 1 #(W-K+2P)/S + 1
    ofmap_dimy = ofmap_dimx
    ofmap_dimc = kernel_shape[0]
    ofmap_shape = (ofmap_dimc,ofmap_dimy,ofmap_dimx)

    parameter_list = {
        "SRAM_ROWS": core_shape[0],
        "SRAM_COLS": core_shape[1],
        "QRACC_INPUT_BITS": ifmap_bits,
        "QRACC_OUTPUT_BITS": ofmap_bits,
        "GB_INT_IF_WIDTH": max(core_shape[1]*ofmap_bits,core_shape[0]*ifmap_bits),
        "FILTER_SIZE_X": kernel_shape[2],
        "FILTER_SIZE_Y": kernel_shape[3],
        "OFMAP_SIZE": np.product(ofmap_shape),
        "IFMAP_SIZE": np.product(ifmap_shape_with_padding),
        "IFMAP_DIMX": ifmap_shape_with_padding[2],
        "IFMAP_DIMY": ifmap_shape_with_padding[3],
        "OFMAP_DIMX": ofmap_dimx,
        "OFMAP_DIMY": ifmap_shape[3],
        "IN_CHANNELS": kernel_shape[1],
        "OUT_CHANNELS": kernel_shape[0],
        "MAPPED_MATRIX_OFFSET_X": 0,
        "MAPPED_MATRIX_OFFSET_Y": 0
    }

    write_parameter_definition_file(parameter_list,param_file_path)

    # Simulation
    run_simulation(simulator,parameter_list,package_list,tb_file,sim_args,rtl_file_list,log_file,run=True)

    return

def test_qracc_ams(
    col_symmetric,
    simulator,
    seed,
    weight_mode,
    wDimX = 32, #nColumns
    wDimY = 128, #nRows
    xBatches = 10,
    xTrits = 1,
    outBits = 4,
    snr_limit = 8,
    run = True, # Set to False to skip RTL simulation
    x_repeat = False
):

    w,x,wx_outBits = generate_qracc_inputs(
        wDimX = wDimX,
        wDimY = wDimY,
        xBatches = xBatches,
        xTrits = xTrits,
        outBits = outBits,
        seed = seed,
        weight_mode = weight_mode,
        col_symmetric = col_symmetric,
        rangeBits = 5,
        x_repeat = x_repeat,
        clip_output = True
    )
    tb_path = 'qracc'
    stimulus_output_path = f'tb/{tb_path}/inputs'

    actual = np.loadtxt(f'{stimulus_output_path}/adc_out_ams_{weight_mode}.txt',dtype=int)
    expected = wx_outBits.T[::-1].T    
    rmse, snr = rmse_snr(expected,actual)
    save_scatter_fig(expected,actual,f'QR Accelerator SNR:{snr:.2f}dB',filename=f'qr_acc_ams_{weight_mode}')

    assert snr > snr_limit, f'SNR: {snr}'

def test_seq_acc_ams(
    col_symmetric,
    simulator,
    seed,
    weight_mode,
    wDimX = 32, #nColumns
    wDimY = 128, #nRows
    xBatches = 10,
    xTrits = 3,
    outBits = 4,
    snr_limit = 8,
    run = True, # Set to False to skip RTL simulation
    x_repeat = False
):
    tb_path = 'seq_acc'
    stimulus_output_path = f'tb/{tb_path}/inputs'

    w,x,wx_outBits = generate_qracc_inputs(
        wDimX = wDimX,
        wDimY = wDimY,
        xBatches = xBatches,
        xTrits = xTrits,
        outBits = outBits,
        seed = seed,
        weight_mode = weight_mode,
        col_symmetric = col_symmetric,
        # rangeBits = 6,
        x_repeat = x_repeat,
        clip_output = False
    )

    actual = np.loadtxt(f'{stimulus_output_path}/mac_out_ams_{weight_mode}.txt',dtype=int)
    expected = wx_outBits.T[::-1].T    
    rmse, snr = rmse_snr(expected,actual)
    save_scatter_fig(expected,actual,f'Sequential Accelerator SNR:{snr:.2f}dB',filename=f'seq_acc_ams_{weight_mode}')

    assert snr > snr_limit, f'SNR: {snr}'


def test_seq_acc(
    col_symmetric,
    simulator,
    seed,
    weight_mode,
    xTrits = 3,
    wDimX = 32, #nColumns
    wDimY = 128, #nRows
    xBatches = 10,
    outBits = 8,
    snr_limit = 8,
    run = True, # Set to False to skip RTL simulation
    x_repeat = False
):
    mac_mode = 1 if weight_mode == 'binary' else 0
  
    package_list = ['../rtl/qracc_pkg.svh']
    rtl_file_list = [ 
        '../rtl/qr_acc_wrapper.sv',
        '../rtl/seq_acc.sv',
        '../rtl/ts_qracc.sv',
        '../rtl/wr_controller.sv',
        '../rtl/twos_to_bipolar.sv'
    ]
    tb_name = 'tb_seq_acc'
    tb_path = 'seq_acc'
    stimulus_output_path = f'tb/{tb_path}/inputs'

    # Pre-simulation
    from tests.stim_lib.stimulus_gen import generate_qracc_inputs

    parameter_list = [
        f'SRAM_ROWS={wDimY}',
        f'SRAM_COLS={wDimX}',
        f'xBits={xTrits+1}',
        f'xBatches={xBatches}',
        f'numAdcBits=4',
        f'macMode={mac_mode}',
        f'outBits={outBits}'
    ]

    print(f'col_symmetric:{col_symmetric}')
    print(f'seed:{seed}')
    print(f'weight_mode:{weight_mode,mac_mode}')
    seed = int(seed) # why do we have to typecast??? weird pytest metaconf thing
    
    w,x,wx_outBits = generate_qracc_inputs(
        wDimX = wDimX,
        wDimY = wDimY,
        xBatches = xBatches,
        xTrits = xTrits,
        outBits = outBits,
        seed = seed,
        weight_mode = weight_mode,
        col_symmetric = col_symmetric,
        rangeBits = 5,
        x_repeat = x_repeat,
        clip_output = False
    )

    # We need to convert the bipolar weights back to binary to write them correctly into hardware
    if weight_mode == 'bipolar':
        w = (w + 1)/2
        w = w.astype(int)

    wint = q.binary_array_to_int(w.T)

    np.savetxt(f'{stimulus_output_path}/w.txt',wint,fmt='%d')
    np.savetxt(f'{stimulus_output_path}/x.txt',x,fmt='%d')
    np.savetxt(f'{stimulus_output_path}/wx_clipped.txt',wx_outBits.T[::-1].T,fmt='%d')

    df = pd.DataFrame
    print('x')
    print(df(x))
    print('w')
    print(df(w.T))
    print('wx >> shift')
    print(df(wx_outBits.T[::-1].T))

    tb_file = f'../tb/{tb_path}/{tb_name}.sv'
    log_file = f'tests/logs/{tb_name}_{simulator}.log'
    
    logdir = os.path.dirname(log_file)
    os.makedirs(logdir,exist_ok=True)

    if simulator == 'vcs':
        parameter_list = [f'-pvalue+{tb_name}.'+p for p in parameter_list]
    else:
        parameter_list = []

    # Simulation

    command = [
            simulator,
            *package_list,
            tb_file
        ] + sim_args[simulator] + rtl_file_list + parameter_list

    print(command)
    print(log_file)
    if run:
        with open(log_file,'w+') as f:
            sim = subprocess.Popen(
            command, 
            shell=False,
            cwd='./sims',
            stdout=f
            )
        assert not sim.wait(), get_log_tail(log_file,10)

    # Post-simulation

    actual = np.loadtxt(f'{stimulus_output_path}/mac_out_rtl_{weight_mode}.txt',dtype=int)
    expected = wx_outBits.T[::-1].T    
    rmse, snr = rmse_snr(expected,actual)
    save_scatter_fig(expected,actual,f'Sequential Accelerator SNR:{snr:.2f}dB',filename=f'seq_acc_{weight_mode}')

    assert snr > snr_limit, f'SNR: {snr}'

    with open(log_file,'r+') as f:
        f.seek(0)
        out = [line for line in f.readlines()]
        assert 'TEST SUCCESS\n' in out, get_log_tail(log_file,10)

    return

def test_tb_qracc(
    col_symmetric,
    simulator,
    seed,
    weight_mode,
    wDimX = 32, #nColumns
    wDimY = 128, #nRows
    xBatches = 10,
    xTrits = 1,
    outBits = 4,
    snr_limit = 8,
    run = True, # Set to False to skip RTL simulation
    x_repeat = False
):
    mac_mode = 1 if weight_mode == 'binary' else 0
  
    package_list = ['../rtl/qracc_pkg.svh']
    rtl_file_list = [ 
        '../rtl/qr_acc_wrapper.sv',
        '../rtl/ts_qracc.sv',
        '../rtl/wr_controller.sv',
        '../rtl/twos_to_bipolar.sv'
    ]
    tb_name = 'tb_qracc'
    tb_path = 'qracc'
    stimulus_output_path = 'tb/qracc/inputs'

    # Pre-simulation
    from tests.stim_lib.stimulus_gen import generate_qracc_inputs

    parameter_list = [
        f'SRAM_ROWS={wDimY}',
        f'SRAM_COLS={wDimX}',
        f'xBits={xTrits+1}',
        f'xBatches={xBatches}',
        f'numAdcBits={outBits}',
        f'macMode={mac_mode}'
    ]

    print(f'col_symmetric:{col_symmetric}')
    print(f'seed:{seed}')
    print(f'weight_mode:{weight_mode,mac_mode}')
    seed = int(seed) # why do we have to typecast??? weird pytest metaconf thing
    
    w,x,wx_outBits = generate_qracc_inputs(
        wDimX = wDimX,
        wDimY = wDimY,
        xBatches = xBatches,
        xTrits = xTrits,
        outBits = outBits,
        seed = seed,
        weight_mode = weight_mode,
        col_symmetric = col_symmetric,
        rangeBits = 5,
        x_repeat = x_repeat
    )

    # We need to convert the bipolar weights back to binary to write them correctly into hardware
    if weight_mode == 'bipolar':
        w = (w + 1)/2
        w = w.astype(int)

    wint = q.binary_array_to_int(w.T)

    np.savetxt(f'{stimulus_output_path}/w.txt',wint,fmt='%d')
    np.savetxt(f'{stimulus_output_path}/x.txt',x,fmt='%d')
    np.savetxt(f'{stimulus_output_path}/wx_4b.txt',wx_outBits.T[::-1].T,fmt='%d')

    df = pd.DataFrame
    print('x')
    print(df(x))
    print('w')
    print(df(w.T))
    print('wx >> shift')
    print(df(wx_outBits.T[::-1].T))

    tb_file = f'../tb/{tb_path}/{tb_name}.sv'
    log_file = f'tests/logs/{tb_name}_{simulator}.log'
    
    logdir = os.path.dirname(log_file)
    os.makedirs(logdir,exist_ok=True)

    if simulator == 'vcs':
        parameter_list = [f'-pvalue+{tb_name}.'+p for p in parameter_list]
    else:
        parameter_list = []

    # Simulation

    command = [
            simulator,
            *package_list,
            tb_file
        ] + sim_args[simulator] + rtl_file_list + parameter_list

    print(command)
    print(log_file)
    if run:
        with open(log_file,'w+') as f:
            sim = subprocess.Popen(
            command, 
            shell=False,
            cwd='./sims',
            stdout=f
            )
        assert not sim.wait(), get_log_tail(log_file,10)

    # Post-simulation

    actual = np.loadtxt(f'{stimulus_output_path}/adc_out_rtl_{weight_mode}.txt',dtype=int)
    expected = wx_outBits.T[::-1].T    
    rmse, snr = rmse_snr(expected,actual)
    save_scatter_fig(expected,actual,f'QR Accelerator SNR:{snr:.2f}dB',filename=f'qr_acc_{weight_mode}')

    assert snr > snr_limit, f'SNR: {snr}'

    with open(log_file,'r+') as f:
        f.seek(0)
        out = [line for line in f.readlines()]
        assert 'TEST SUCCESS\n' in out, get_log_tail(log_file,10)

    return

def test_tb_column(simulator,run=True):
    package_list = ['../rtl/qracc_pkg.svh']
    rtl_file_list = [ 
        "../rtl/column_wrapper.sv", 
        "../rtl/wr_controller.sv", 
        "../rtl/ts_column.sv",
    ]
    tb_name = 'tb_column'
    tb_file = f'../tb/{tb_name}.sv'
    log_file = f'tests/logs/{tb_name}.log'
    parameter_list = []

    command = [
            simulator,
            *package_list,
            tb_file
        ] + sim_args[simulator] + rtl_file_list + parameter_list
    
    logdir = os.path.dirname(log_file)
    os.makedirs(logdir,exist_ok=True)

    print(command)

    if run:
        with open(log_file,'w+') as f:
            sim = subprocess.Popen(
            command, 
            shell=False,
            cwd='./sims',
            stdout=f
            )
            assert not sim.wait(), get_log_tail(log_file,10)

    with open(log_file,'r+') as f:
        f.seek(0)
        out = [line for line in f.readlines()]
        assert 'TEST SUCCESS\n' in out, get_log_tail(log_file,10)

def test_tb_q_redis():

    rtl_file_list = [ ]
    tb_name = 'tb_q_redis'

    tb_file = f'../tb/{tb_name}.sv'
    log_file = f'tests/logs/{tb_name}.log'
    
    logdir = os.path.dirname(log_file)
    os.makedirs(logdir,exist_ok=True)

    with open(log_file,'w+') as f:

        xcel = subprocess.Popen([
            "xrun", 
            "+access+r",
            tb_file
        ] + rtl_file_list, 
        shell=False,
        cwd='./sims',
        stdout=f
        )

    assert not xcel.wait(), get_log_tail(log_file,10)

    with open(log_file,'r+') as f:
        f.seek(0)
        out = [line for line in f.readlines()]
        assert 'TEST SUCCESS\n' in out, get_log_tail(log_file,10)

def get_log_tail(log_file,lines):
    print(f'See {log_file} for details') 
    with open(log_file,'r') as f:
        lines = f.readlines()[-lines:]
        return ''.join(lines)

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
        x=expected.flatten(), 
        y=actual.flatten(),
        size=1,
        legend=False
    )
    ax.set_title(title)
    ax.set_xlabel('Actual')
    ax.set_ylabel('Ideal')
    lim = [expected.min(),expected.max()]
    sns.lineplot(x=lim,y=lim,color='gray',linestyle='--')
    plt.tight_layout()
    plt.savefig(f'images/{filename}.svg')
    plt.savefig(f'images/png/{filename}.png')