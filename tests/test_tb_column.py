
import subprocess
import os
import sys
from sclibs import lib_file_list 

def test_tb_column():

    rtl_file_list = [ 
        "../rtl/qr_acc_wrapper.sv", 
        "../rtl/wr_controller.sv", 
        "../rtl/qrAcc.sv",
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
        assert 'TEST SUCCESS\n' in out

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

    assert not xcel.wait()

    with open(log_file,'r+') as f:
        f.seek(0)
        out = [line for line in f.readlines()]
        assert 'TEST SUCCESS\n' in out

# TODO: Make QRMac accelerator and testbench
def test_tb_qrmac():

    rtl_file_list = [ 
        "../rtl/qr_acc_wrapper.sv", 
        "../rtl/wr_controller.sv", 
        "../rtl/qrAcc.sv",
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
        assert 'TEST SUCCESS\n' in out
