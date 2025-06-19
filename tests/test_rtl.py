
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
from tests.stim_lib.compile import bundle_config_into_write, make_trigger_write, write_array_to_asm

# simulator = 'xrun'
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
    ('fc_pointwise',    (1,3,16,16),   (32,3,1,1),     (256,256),  1,          1,      0,          0,          False),           
    ('fc_pw_long',      (1,40,16,16),  (32,40,1,1),    (256,256),  1,          1,      0,          0,          False),   
    ('depthwise',       (1,32,16,16),  (32,1,3,3),     (256,256),  1,          1,      0,          0,          True),
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
    ifmap_bits = 8, 
    kernel_bits = 1,
    ofmap_bits = 8,
    soft_padding = False,
    snr_limit = 1 # We get really poor SNR due to MBL value clipping. Need signed weights. See issue.
): 
    weight_mode = 'bipolar'
    mac_mode = 1 if weight_mode == 'binary' else 0

    config_write_address = '00000010'

    # Pointwise convolutions do not pad or stride
    if kernel_shape[2] == 1 and kernel_shape[3] == 1:
        padding = 0
        stride = 1
  
    package_list = ['../rtl/qracc_params.svh','../rtl/qracc_pkg.svh']
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
    print(f'raw_data, stimulus = generate_hexes('
        f'savepath = None, '
        f'stride = {stride}, '
        f'ifmap_shape = {ifmap_shape}, '
        f'ifmap_bits = {ifmap_bits}, '
        f'kernel_shape = {kernel_shape}, '
        f'kernel_bits = {kernel_bits}, '
        f'core_shape = {core_shape}, '
        f'padding = {padding}, '
        f'mm_offset_x = {mm_offset_x}, '
        f'mm_offset_y = {mm_offset_y}, '
        f'soft_padding = {soft_padding}, '
        f'depthwise={depthwise})'
    )
    raw_data, stimulus = generate_hexes(
        savepath = stimulus_output_path,
        stride = stride,
        ifmap_shape = ifmap_shape,
        ifmap_bits = ifmap_bits,
        kernel_shape = kernel_shape,
        kernel_bits = kernel_bits,
        core_shape = core_shape,
        padding = padding,
        mm_offset_x = mm_offset_x,
        mm_offset_y = mm_offset_y, 
        soft_padding = soft_padding, 
        depthwise=depthwise
    )
    ifmap_shape_with_padding = (ifmap_shape[0],ifmap_shape[1],ifmap_shape[2]+2*padding,ifmap_shape[3]+2*padding)
    ofmap_dimx = ((ifmap_shape[2] - kernel_shape[2] + 2*padding) // stride) + 1 #(W-K+2P)/S + 1
    ofmap_dimy = ofmap_dimx
    ofmap_dimc = kernel_shape[0]
    ofmap_shape = (ofmap_dimc,ofmap_dimy,ofmap_dimx)

    # Infer optimal ADC reference range shifts
    adc_ref_range_shifts = infer_optimal_adc_range_shifts(stimulus['toeplitz'][0], stimulus['small_matrix'], ifmap_bits) if not depthwise else 0
    # no need for adc_ref_range_shifts for depthwise convolutions, since we don't do IMC for that

    parameter_list = {
        "SRAM_ROWS": core_shape[0],
        "SRAM_COLS": core_shape[1],
        "QRACC_INPUT_BITS": ifmap_bits,
        "QRACC_OUTPUT_BITS": ofmap_bits,
        # "GB_INT_IF_WIDTH": max(core_shape[1]*ofmap_bits,core_shape[0]*ifmap_bits),
        "GB_INT_IF_WIDTH": 32*8, # enough for a single bank
        "FILTER_SIZE_X": kernel_shape[2],
        "FILTER_SIZE_Y": kernel_shape[3],
        "OFMAP_SIZE": np.prod(ofmap_shape),
        "IFMAP_SIZE": np.prod(ifmap_shape) if not soft_padding else np.prod(ifmap_shape_with_padding),
        "IFMAP_DIMX": ifmap_shape[2],
        "IFMAP_DIMY": ifmap_shape[3],
        "OFMAP_DIMX": ofmap_dimx,
        "OFMAP_DIMY": ofmap_dimy,
        "IN_CHANNELS": kernel_shape[1],
        "OUT_CHANNELS": kernel_shape[0],
        "MAPPED_MATRIX_OFFSET_X": mm_offset_x,
        "MAPPED_MATRIX_OFFSET_Y": mm_offset_y,
        "STRIDE_X": stride,
        "STRIDE_Y": stride,
        "UNSIGNED_ACTS": 1,
        "NUM_ADC_REF_RANGE_SHIFTS": int(adc_ref_range_shifts)
    }
    
    print(f'Parameter list: {parameter_list}')
    write_parameter_definition_file(parameter_list,param_file_path)

    # Config
    config_dict = {
        "n_input_bits_cfg": ifmap_bits,
        "n_output_bits_cfg": ofmap_bits,
        "unsigned_acts": 1,
        "binary_cfg": 1,
        "adc_ref_range_shifts": int(adc_ref_range_shifts),
        "filter_size_y": kernel_shape[3],
        "filter_size_x": kernel_shape[2],
        "input_fmap_dimx": ifmap_shape[2] if not soft_padding else ifmap_shape_with_padding[2],
        "input_fmap_dimy": ifmap_shape[3] if not soft_padding else ifmap_shape_with_padding[3],
        "output_fmap_dimx": ofmap_dimx,
        "output_fmap_dimy": ofmap_dimy,
        "stride_x": stride,
        "stride_y": stride,
        "num_input_channels": ifmap_shape[1],
        "num_output_channels": kernel_shape[0],
        "mapped_matrix_offset_x": mm_offset_x,
        "mapped_matrix_offset_y": mm_offset_y,
        "padding": padding if not soft_padding else 0,  # Use 0 padding for soft padding
        "padding_value": stimulus["scaler_params"]["zp_x"],  # Padding value for the input feature map
    }
    print(f"Config Dict: {config_dict}")
    config_writes = bundle_config_into_write(config_dict, config_write_address)

    commands = config_writes
    if depthwise:
        commands += make_trigger_write('TRIGGER_LOADWEIGHTS_PERIPHS_DIGITAL', write_address=config_write_address)
    else:
        commands += make_trigger_write('TRIGGER_LOADWEIGHTS_PERIPHS', write_address=config_write_address)
    commands += write_array_to_asm(raw_data['weights']) 
    commands += write_array_to_asm(raw_data['scales']) 
    commands += write_array_to_asm(raw_data['biases']) 
    commands += make_trigger_write('TRIGGER_LOAD_ACTIVATION', write_address=config_write_address)
    commands += write_array_to_asm(raw_data['ifmap'])
    if depthwise:
        commands += make_trigger_write('TRIGGER_COMPUTE_DIGITAL', write_address=config_write_address)
    else:
        commands += make_trigger_write('TRIGGER_COMPUTE_ANALOG', write_address=config_write_address)
    commands += [f'WAITBUSY']
    commands += make_trigger_write('TRIGGER_READ_ACTIVATION', write_address=config_write_address)
    commands += [f'WAITREAD']
    commands += ['END']

    with open(f'{stimulus_output_path}/commands.txt', 'w') as f:
        for write in commands:
            f.write(write + '\n')

    # Simulation
    run_simulation(simulator,{},package_list,tb_file,sim_args,rtl_file_list,log_file,run=True)

    # Post-simulation
    acc_result_flat = np.loadtxt("tb/qracc_top/outputs/hw_ofmap.txt", dtype=int)
    result_shape = np.loadtxt("tb/qracc_top/inputs/result_shape.txt", dtype=int)
    acc_result = acc_result_flat.reshape(*result_shape)

    rmse, snr = rmse_snr(stimulus['result'], acc_result)
    save_scatter_fig(expected = stimulus['result'],actual = acc_result, title = f"{stimulus['small_matrix'].shape} SNR {snr:.3f} dB",filename =  f"{test_name}_snr")
    print(acc_result.shape, stimulus['result'].shape)
    # plot_diff_channels(acc_result - stimulus['result'], tensor_format='NHWC', filename=f'{test_name}_channels')
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
    # plt.savefig(f'images/{filename}.svg') # Saving scatter plots to SVG is a little too slow
    plt.savefig(f'images/png/{filename}.png')
    plt.close()

def plot_diff_channels(diff, tensor_format='NCHW', filename='diff_channels', bitPrecision=8):
    """
    Plots all channels of the diff tensor in a subplot grid.

    Parameters:
    - diff: numpy.ndarray, the tensor to plot
    - tensor_format: str, format of the tensor ('NCHW' or 'NHWC')
    - bitPrecision: int, bit precision for value range (default 8)
    """
    if tensor_format == 'NHWC':
        diff_2plot = diff.transpose(0, 3, 1, 2)  # Convert to NCHW format for plotting

    num_channels = diff_2plot.shape[1]  # Number of channels in the last dimension
    rows = (num_channels + 7) // 8  # Calculate rows for 8 columns
    fig, axs = plt.subplots(rows, 8, figsize=(20, 10), dpi=200)
    axs = axs.flatten()  # Flatten the axes array for easier indexing
    vmin, vmax = 0, 2**bitPrecision - 1

    for i in range(num_channels):
        ax = axs[i]
        im = ax.imshow(diff_2plot[0, i], vmin=vmin, vmax=vmax, cmap='YlOrBr')
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

    plt.savefig(f'images/{filename}.svg', bbox_inches='tight')
    plt.savefig(f'images/png/{filename}.png', bbox_inches='tight')
    plt.close()
