
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

def test_tb_qracc(simulator='xrun'):

    package_list = []
    rtl_file_list = [ 
        '../rtl/qr_acc_wrapper.sv',
        '../rtl/ts_qracc.sv',
        '../rtl/wr_controller.sv',
    ]
    tb_name = 'tb_qracc'
    tb_path = 'qracc'
    stimulus_output_path = 'tb/qracc/inputs'

    # Pre-simulation
    from tests.stim_lib.stimulus_gen import generate_qracc_inputs

    w,x,wx_outBits = generate_qracc_inputs(
        wDimX = 8, #nColumns
        wDimY = 128, #nRows
        xBatches = 50,
        xTrits = 4,
        outBits = 4,
        seed = 0,
        weight_mode = 'binary'
    )

    wint = q.binary_array_to_int(w)

    np.savetxt(f'{stimulus_output_path}/w.txt',wint,fmt='%d')
    np.savetxt(f'{stimulus_output_path}/x.txt',x.T,fmt='%d')
    np.savetxt(f'{stimulus_output_path}/wx_4b.txt',wx_outBits,fmt='%d')

    tb_file = f'../tb/{tb_path}/{tb_name}.sv'
    log_file = f'tests/logs/{tb_name}_{simulator}.log'
    
    logdir = os.path.dirname(log_file)
    os.makedirs(logdir,exist_ok=True)

    # Simulation

    with open(log_file,'w+') as f:

        sim = subprocess.Popen([
            simulator,
            *package_list,
            tb_file
        ] + sim_args[simulator] + rtl_file_list, 
        shell=False,
        cwd='./sims',
        stdout=f
        )

    assert not sim.wait(), get_log_tail(log_file,10)

    # Post-simulation

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