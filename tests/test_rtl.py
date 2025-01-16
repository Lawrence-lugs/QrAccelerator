
import subprocess
import os
import sys
import hwacctools.quantization.quant as q
import numpy as np

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

def test_tb_qracc(
    simulator='vcs',
    tolerance = 0.1,
    wDimX = 32, #nColumns
    wDimY = 128, #nRows
    xBatches = 50,
    xTrits = 1,
    outBits = 4,
    seed = 0,
    weight_mode = 'binary',
    rmse_limit = 0.1,
    run = True # Set to False to skip RTL simulation
):
    mac_mode = 1 if weight_mode == 'binary' else 0
  
    package_list = []
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
    
    w,x,wx_outBits = generate_qracc_inputs(
        wDimX = wDimX,
        wDimY = wDimY,
        xBatches = xBatches,
        xTrits = xTrits,
        outBits = outBits,
        seed = seed,
        weight_mode = weight_mode
    )

    wint = q.binary_array_to_int(w)

    np.savetxt(f'{stimulus_output_path}/w.txt',wint,fmt='%d')
    np.savetxt(f'{stimulus_output_path}/x.txt',x,fmt='%d')
    np.savetxt(f'{stimulus_output_path}/wx_4b.txt',wx_outBits,fmt='%d')

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

    if run:
        with open(log_file,'w+') as f:
            sim = subprocess.Popen([
                simulator,
                *package_list,
                tb_file
            ] + sim_args[simulator] + rtl_file_list + parameter_list, 
            shell=False,
            cwd='./sims',
            stdout=f
            )
        assert not sim.wait(), get_log_tail(log_file,10)

    # Post-simulation

    adc_out = np.loadtxt(f'{stimulus_output_path}/adc_out.txt',dtype=int)
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

def test_tb_column():

    rtl_file_list = [ 
        "../rtl/qr_acc_wrapper.sv", 
        "../rtl/wr_controller.sv", 
        "../rtl/ts_column.sv",
    ]
    tb_name = 'tb_column'

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

    assert not xcel.wait()

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

# def test_tb_qrmac():

#     rtl_file_list = [ 
#         "../rtl/qr_acc_wrapper.sv", 
#         "../rtl/wr_controller.sv", 
#         "../rtl/ts_column.sv",
#     ]
#     tb_name = 'tb_column'

#     tb_file = f'../tb/{tb_name}.sv'
#     log_file = f'tests/logs/{tb_name}.log'
    
#     logdir = os.path.dirname(log_file)
#     os.makedirs(logdir,exist_ok=True)

#     with open(log_file,'w+') as f:

#         xcel = subprocess.Popen([
#             "xrun", 
#             "+access+r",
#             tb_file
#         ] + rtl_file_list, 
#         shell=False,
#         cwd='./sims',
#         stdout=f
#         )

#     assert not xcel.wait(), get_log_tail(log_file,10)

#     with open(log_file,'r+') as f:
#         f.seek(0)
#         out = [line for line in f.readlines()]
#         assert 'TEST SUCCESS\n' in out, get_log_tail(log_file,10)

def get_log_tail(log_file,lines):
    print(f'See {log_file} for details') 
    with open(log_file,'r') as f:
        lines = f.readlines()[-lines:]
        return ''.join(lines)