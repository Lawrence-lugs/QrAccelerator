
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
from .utils import *

@pytest.mark.parametrize(
    "test_name,         ifmap_shape,   kernel_shape,   core_shape, padding,    stride, mm_offset_x,mm_offset_y, depthwise",[
    ('singlebank',      (1,3,16,16),   (32,3,3,3),     (256,32),   1,          1,      0,          0,          False),           
    ('offsetx',         (1,3,16,16),   (32,3,3,3),     (256,256),  1,          1,      30,         0,          False),           
    ('offsetxy',        (1,3,16,16),   (32,3,3,3),     (256,256),  1,          1,      69,         38,         False),          
    ('fc_offsetxy',     (1,16,16,16),  (64,16,3,3),    (256,256),  1,          1,      69,         38,         False),          
    ('morethan32fload', (1,16,16,16),  (32,16,3,3),    (256,32),   1,          1,      0,          0,          False),           
    ('fc_smallload',    (1,3,16,16),   (32,3,3,3),     (256,256),  1,          1,      0,          0,          False),           
    ('fc_fullload',     (1,27,16,16),  (256,27,3,3),   (256,256),  1,          1,      0,          0,          False),           
    ('fc_wideload',     (1,3,16,16),   (256,3,3,3),    (256,256),  1,          1,      0,          0,          False),           
    ('fc_wide_2s',      (1,3,16,16),   (256,3,3,3),    (256,256),  1,          2,      0,          0,          False),           
    ('fc_pw',           (1,3,16,16),   (32,3,1,1),     (256,256),  1,          1,      0,          0,          False),           
    ('fc_pw_long',      (1,40,16,16),  (32,40,1,1),    (256,256),  1,          1,      0,          0,          False),   
    ('depthwise',       (1,32,16,16),  (32,1,3,3),     (256,256),  1,          1,      0,          0,          True),
    ('dw_nopad',        (1,32,16,16),  (32,1,3,3),     (256,256),  0,          1,      0,          0,          True),
    ('dw_short',        (1,16,16,16),  (16,1,3,3),     (256,256),  1,          1,      0,          0,          True),
])
def test_qr_acc_top_single_load(
    col_symmetric,
    simulator,
    seed,
    test_name,
    kernel_shape, 
    ifmap_shape,
    core_shape,
    padding,
    stride,
    mm_offset_x,
    mm_offset_y,
    depthwise,
    ifmap_bits    = 8,
    kernel_bits   = 1,
    ofmap_bits    = 8,
    soft_padding  = False,
    snr_limit     = 1,     # We get really poor SNR due to MBL value clipping. Need signed weights. See issue #28 and #13.
    model_mem     = True,
    post_synth    = True,
    nodump        = False,
    noiofiles     = True,
    notplitztrack = True,
): 
    
    run_read_but_noio = False
    if post_synth: 
        model_mem = False # Post-synthesis does not support model memory
        notplitztrack = True # Post-synthesis does not support toeplitz tracking
        if not noiofiles:
            run_read_but_noio = True # Run the read state regardless of noiofiles
        noiofiles = True # Post-synthesis does not support I/O files

    # Pointwise convolutions do not pad or stride
    if kernel_shape[2] == 1 and kernel_shape[3] == 1:
        padding = 0
        stride = 1

    add_libs = not model_mem or post_synth
  
    lib_list = [os.getenv('SYNTH_LIB'), os.getenv('SRAM_FILES')] if add_libs else []
    package_list = lib_list + ['../rtl/qracc_params.svh','../rtl/qracc_pkg.svh']
    rtl_file_list = [
        '../rtl/activation_buffer/piso_write_queue.sv',
        '../rtl/activation_buffer/mm_output_aligner.sv',
        '../rtl/wsacc/wsacc_pe_cluster.sv',
        '../rtl/wsacc/wsacc_pe.sv',
        '../rtl/qr_acc_wrapper.sv',
        '../rtl/seq_acc.sv',
        '../rtl/ts_qracc.sv',
        '../rtl/wr_controller.sv',
        '../rtl/twos_to_bipolar.sv',
        '../rtl/ts_qracc_multibank.sv',
        '../rtl/qr_acc_top.sv',
        '../rtl/output_scaler/output_scaler_set.sv',
        '../rtl/output_scaler/output_scaler.sv',
        '../rtl/memory/ram_2w2r.sv',
        '../rtl/feature_loader/feature_loader.sv',
        '../rtl/feature_loader/padder.sv',
        '../rtl/control/qracc_csr.sv',
        '../rtl/control/qracc_controller.sv',
    ] if not post_synth else [
        '../rtl/ts_qracc.sv',
        '../rtl/ts_qracc_multibank.sv',
        '../rtl/control/qracc_csr.sv',
        '../synth/mapped/mapped_qr_acc_top.v'
    ]

    if not model_mem:
        rtl_file_list += [
        '../rtl/activation_buffer/activation_buffer.sv','../rtl/activation_buffer/sram_32bank_8b.sv']

    tb_name = 'tb_qracc_top'
    tb_path = 'qracc_top'
    stimulus_output_path = f'tb/{tb_path}/inputs'
    empty_directory(stimulus_output_path)
    param_file_path = 'rtl/qracc_params.svh'

    # Setup log paths
    tb_file = f'../tb/{tb_path}/{tb_name}.sv'
    log_file = f'tests/logs/{tb_name}_{simulator}.log'
    logdir = os.path.dirname(log_file)
    os.makedirs(logdir,exist_ok=True)

    # Parameters are bound to the specific hardware configuration
    parameter_list = {
        "SRAM_ROWS": core_shape[0],
        "SRAM_COLS": core_shape[1],
        "QRACC_INPUT_BITS": 8,
        "QRACC_OUTPUT_BITS": 8,
        "GB_INT_IF_WIDTH": 32*8, # enough for a single bank
    }
    if notplitztrack:
        parameter_list['NOTPLITZTRACK'] = 1
    if nodump:
        parameter_list['NODUMP'] = 1
    if noiofiles:
        parameter_list['NOIOFILES'] = 1
    if model_mem:
        parameter_list['MODEL_MEM'] = 1
    if post_synth:
        parameter_list['POST_SYNTH'] = 1
    if run_read_but_noio:
        parameter_list['RUN_READ_BUT_NOIO'] = 1

    print(f'Parameter list: {parameter_list}')
    write_parameter_definition_file(parameter_list,param_file_path)

    print(f'u_code = QrAccNodeCode.produce_single_node_test('
        f'ifmap_shape = {ifmap_shape}, '
        f'kernel_shape = {kernel_shape}, '
        f'offset_x = {mm_offset_x}, '
        f'offset_y = {mm_offset_y}, '
        f'core_size = {core_shape}, '
        f'ws_core_size = 32, '
        f'pads = ({padding}, {padding}, {padding}, {padding}), '
        f'stride = ({stride}, {stride}), '
        f'depthwise = {depthwise})')

    u_code = QrAccNodeCode.produce_single_node_test(
        ifmap_shape  = ifmap_shape,
        kernel_shape = kernel_shape,
        offset_x     = mm_offset_x,
        offset_y     = mm_offset_y,
        core_size    = core_shape,
        ws_core_size = 32,
        pads         = (padding, padding, padding, padding),
        stride       = (stride, stride),
        depthwise    = depthwise,
    )

    print(u_code)

    commands = u_code.compile()
    with open(f'{stimulus_output_path}/commands.txt', 'w') as f:
        for write in commands:
            f.write(write + '\n')

    if 'NOIOFILES' not in parameter_list.keys():
        u_code.write_files(stimulus_output_path)

    # Simulation
    run_simulation(simulator,{},package_list,tb_file,sim_args,rtl_file_list,log_file,run=True)

    # Post-simulation
    if 'NOIOFILES' in parameter_list.keys():
        print('Skipping output file check')
        return
    acc_result_flat = np.loadtxt("tb/qracc_top/outputs/hw_ofmap.txt", dtype=int)
    result_shape = np.loadtxt("tb/qracc_top/inputs/result_shape.txt", dtype=int)
    acc_result = acc_result_flat.reshape(*result_shape)

    rmse, snr = rmse_snr(u_code.reference_output, acc_result)
    # save_scatter_fig(expected = u_code.reference_output,actual = acc_result, title = f"{u_code.matrix.shape} SNR {snr:.3f} dB",filename =  f"{test_name}_snr")
    # plot_diff_channels(acc_result - u_code.reference_output, tensor_format='NHWC', filename=f'{test_name}_channels')
    assert snr > snr_limit, f'SNR: {snr}'

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

# @pytest.mark.parametrize("unsigned_acts", [True, False])
# @pytest.mark.parametrize("xTrits", [1, 3, 7])

@pytest.mark.parametrize(
     "unsigned_acts,xBits,wDimX,wDimY,outBits", [
    (         False,    2,   32,  128,       8,),
    (         False,    4,   32,  128,       8,),
    (         False,    8,   32,  128,       8,),
    (          True,    2,   32,  128,       8,),
    (          True,    4,   32,  128,       8,),
    (          True,    8,   32,  128,       8,),
])
def test_seq_acc(
    simulator,
    seed,
    weight_mode,
    unsigned_acts,
    xBits,
    wDimX, #nColumns
    wDimY, #nRows
    outBits,
    xBatches = 10,
    snr_limit = 8,
    run = True, # Set to False to skip RTL simulation
    col_symmetric = False,
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

    xTrits = xBits if unsigned_acts else xBits - 1

    parameter_list = [
        f'SRAM_ROWS={wDimY}',
        f'SRAM_COLS={wDimX}',
        f'xBits={xBits}',
        f'xBatches={xBatches}',
        f'numAdcBits=4',
        f'macMode={mac_mode}',
        f'outBits={outBits}',
        f'unsignedActs={int(unsigned_acts)}',
    ]

    print(f'col_symmetric:{col_symmetric}')
    print(f'seed:{seed}')
    print(f'weight_mode:{weight_mode,mac_mode}')
    seed = int(seed) # why do we have to typecast??? weird pytest metaconf thing

    print(f"w,x,wx_outBits = generate_qracc_inputs(wDimX = {wDimX}, wDimY = {wDimY}, xBatches = {xBatches}, xTrits = {xTrits}, outBits = {outBits}, seed = {seed}, weight_mode = '{weight_mode}', col_symmetric = {col_symmetric}, rangeBits = 5, x_repeat = {x_repeat}, clip_output = False, unsigned_acts = {unsigned_acts})")
    
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
        clip_output = False,
        unsigned_acts = unsigned_acts,
        bitRange = None
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

    # print command as list with strings
    print('=====VCS COMMAND=====')
    print(' '.join(command))
    print('=====================')

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
