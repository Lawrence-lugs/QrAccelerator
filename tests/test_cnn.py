# import subprocess
# import os
# import sys
# import hwacctools.quantization.quant as q
# import numpy as np
# import pandas as pd
# import matplotlib.pyplot as plt
# import seaborn as sns
# import pytest
# sns.set_theme()
# from tests.stim_lib.stimulus_gen import *
# from test_rtl import *

# def test_qr_acc_top_packed_bins(
#     col_symmetric,
#     simulator,
#     seed,
#     test_name,
#     kernel_shape, 
#     ifmap_shape,
#     core_shape,
#     ifmap_bits = 8, 
#     kernel_bits = 1,
#     ofmap_bits = 8,
#     snr_limit = 1 # We get really poor SNR due to MBL value clipping. Need signed weights. See issue.
# ):  
#     weight_mode = 'bipolar'
#     mac_mode = 1 if weight_mode == 'binary' else 0
  
#     package_list = ['../rtl/qracc_params.svh','../rtl/qracc_pkg.svh']
#     rtl_file_list = [ 
#         '../rtl/activation_buffer/piso_write_queue.sv',
#         '../rtl/activation_buffer/mm_output_aligner.sv',
#         '../rtl/qr_acc_wrapper.sv',
#         '../rtl/seq_acc.sv',
#         '../rtl/ts_qracc.sv',
#         '../rtl/wr_controller.sv',
#         '../rtl/twos_to_bipolar.sv',
#         '../rtl/ts_qracc_multibank.sv',
#         '../rtl/qr_acc_top.sv',
#         '../rtl/output_scaler/output_scaler_set.sv',
#         '../rtl/output_scaler/output_scaler.sv',
#         '../rtl/memory/ram_2w2r.sv',
#         '../rtl/feature_loader/feature_loader.sv',
#         '../rtl/control/qracc_controller.sv'
#     ]
#     tb_name = 'tb_qracc_top'
#     tb_path = 'qracc_top'
#     stimulus_output_path = f'tb/{tb_path}/inputs'
#     param_file_path = 'rtl/qracc_params.svh'

#     # Setup log paths
#     tb_file = f'../tb/{tb_path}/{tb_name}.sv'
#     log_file = f'tests/logs/{tb_name}_{simulator}.log'
#     logdir = os.path.dirname(log_file)
#     os.makedirs(logdir,exist_ok=True)

#     # Pre-simulation
#     print('')
#     print(f"stimulus = generate_top_inputs(stimulus_output_path,{stride},{ifmap_shape},{ifmap_bits},{kernel_shape},{kernel_bits},{core_shape})")
#     stimulus = generate_top_inputs(stimulus_output_path,stride,ifmap_shape,ifmap_bits,kernel_shape,kernel_bits,core_shape,mm_offset_x,mm_offset_y)
    
#     ifmap_shape_with_padding = (ifmap_shape[0],ifmap_shape[1],ifmap_shape[2]+2*padding,ifmap_shape[3]+2*padding)

#     ofmap_dimx = ((ifmap_shape[2] - kernel_shape[2] + 2*padding) // stride) + 1 #(W-K+2P)/S + 1
#     ofmap_dimy = ofmap_dimx
#     ofmap_dimc = kernel_shape[0]
#     ofmap_shape = (ofmap_dimc,ofmap_dimy,ofmap_dimx)

#     # Infer optimal ADC reference range shifts
#     first_partials = q.int_to_trit(stimulus['toeplitz'][0],ifmap_bits).T @ stimulus['small_matrix']
#     mean_partial = first_partials.mean()
#     adc_ref_range_shifts = np.ceil(np.log(mean_partial)/np.log(2)) - 3
#     if adc_ref_range_shifts < 0:
#         adc_ref_range_shifts = 0

#     parameter_list = {
#         "SRAM_ROWS": core_shape[0],
#         "SRAM_COLS": core_shape[1],
#         "QRACC_INPUT_BITS": ifmap_bits,
#         "QRACC_OUTPUT_BITS": ofmap_bits,
#         # "GB_INT_IF_WIDTH": max(core_shape[1]*ofmap_bits,core_shape[0]*ifmap_bits),
#         "GB_INT_IF_WIDTH": 32*8, # enough for a single bank
#         "FILTER_SIZE_X": kernel_shape[2],
#         "FILTER_SIZE_Y": kernel_shape[3],
#         "OFMAP_SIZE": np.prod(ofmap_shape),
#         "IFMAP_SIZE": np.prod(ifmap_shape_with_padding),
#         "IFMAP_DIMX": ifmap_shape_with_padding[2],
#         "IFMAP_DIMY": ifmap_shape_with_padding[3],
#         "OFMAP_DIMX": ofmap_dimx,
#         "OFMAP_DIMY": ifmap_shape[3],
#         "IN_CHANNELS": kernel_shape[1],
#         "OUT_CHANNELS": kernel_shape[0],
#         "MAPPED_MATRIX_OFFSET_X": mm_offset_x,
#         "MAPPED_MATRIX_OFFSET_Y": mm_offset_y,
#         "UNSIGNED_ACTS": 1,
#         "NUM_ADC_REF_RANGE_SHIFTS": int(adc_ref_range_shifts)
#     }

#     print(f'Parameter list: {parameter_list}')

#     write_parameter_definition_file(parameter_list,param_file_path)

#     # Simulation
#     run_simulation(simulator,{},package_list,tb_file,sim_args,rtl_file_list,log_file,run=True)

#     # Post-simulation

#     acc_result_flat = np.loadtxt("tb/qracc_top/outputs/hw_ofmap.txt", dtype=int)
#     result_shape = np.loadtxt("tb/qracc_top/inputs/result_shape.txt", dtype=int)
#     acc_result = acc_result_flat.reshape(*result_shape)

#     rmse, snr = rmse_snr(stimulus['result'], acc_result)
#     save_scatter_fig(expected = stimulus['result'],actual = acc_result, title = f"QRAccLinearConv SNR {snr}",filename =  f"{test_name}_snr")
#     plot_diff_channels(acc_result - stimulus['result'], tensor_format='NHWC', filename=f'{test_name}_channels')
#     assert snr > snr_limit, f'SNR: {snr}'

#     return