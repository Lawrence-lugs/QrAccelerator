
import subprocess
import os
import sys
import hwacctools.quantization.quant as q
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
sns.set_theme()

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

def test_seq_acc(
    col_symmetric,
    simulator,
    seed,
    weight_mode,
    wDimX = 32, #nColumns
    wDimY = 128, #nRows
    xBatches = 10,
    xTrits = 3,
    outBits = 8,
    rmse_limit = 0.5,
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
        rangeBits = 6,
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

    mac_out = np.loadtxt(f'{stimulus_output_path}/mac_out.txt',dtype=int)
    np.savetxt(f'{stimulus_output_path}/mac_out_rtlsims.txt',mac_out,fmt='%d')
    exp_out = wx_outBits.T[::-1].T

    # Compute RMSE
    rmse = np.sqrt(np.mean((mac_out - exp_out)**2)) 
    print(f'RMSE:{rmse}')

    assert rmse < rmse_limit, f'RMSE: {rmse}'

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
    rmse_limit = 0.5,
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
        rangeBits = 6,
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

    adc_out = np.loadtxt(f'{stimulus_output_path}/adc_out.txt',dtype=int)
    np.savetxt(f'{stimulus_output_path}/adc_out_rtlsims.txt',adc_out,fmt='%d')
    exp_out = wx_outBits.T[::-1].T

    # Compute RMSE
    rmse = np.sqrt(np.mean((adc_out - exp_out)**2))
    print(f'RMSE:{rmse}')
    assert rmse < rmse_limit, f'RMSE: {rmse}'

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