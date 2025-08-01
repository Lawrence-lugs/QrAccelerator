import numpy as np
from tests.stim_lib.stimulus_gen import *
from tests.stim_lib.compile import *
from hwacctools.comp_graph import compute, cgraph, cnodes, core, packer_utils as pu
from hwacctools.onnx_tools import onnx_splitter
import hwacctools.onnx_utils as onnx_utils
import hwacctools.quantization.quant as quant
import pytest
from .utils import *

def get_single_node_marp_code(
    mnode_index,
    modelpath = 'onnx_models/mbv2_cifar10_int8_binary.onnx',
    imc_core_size = (256, 256),
    dwc_core_size = 32,
):    
    # Running a single node from a model
    nx_model = onnx.load(modelpath)

    u_nx_mapping = core.NxModelMapping(
        nx_model,
        imc_core_size=imc_core_size,
        dwc_core_size=dwc_core_size
    )

    np.random.seed(0)  # For reproducibility
    input_dict = {
        'input.1': np.random.rand(1, 3, 32, 32).astype(np.float32)
    }

    node = u_nx_mapping.mapped_nodes[mnode_index]
    node_id = node.node_id
    bin = u_nx_mapping.mapped_bins[node.bin_id] if not node.depthwise else None

    input_tensor_shape = onnx_utils.get_intermediate_tensor_value(
        nx_model, nx_model.graph.node[node_id].input[0], input_dict=input_dict).shape
    input_tensor = np.random.randint(0, 256, input_tensor_shape).astype(np.uint8)

    u_code = QrAccNodeCode(
        mapped_node = node,
        mapped_bin = bin,
        ifmap = input_tensor,
        imc_core_size = imc_core_size,
        ws_core_size = dwc_core_size,
        nx_model = nx_model
    )

    return u_code

@pytest.mark.parametrize(
    "mnode_index",
    [0, 1, 2, 3, 4, 308, 309, 310]
)
def test_qracc_with_onnx_single_node(
    simulator,
    mnode_index,
    modelpath = 'onnx_models/mbv2_cifar10_int8_binary.onnx',
    imc_core_size = (256, 256),
    dwc_core_size = 32,
):    
    
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
    empty_directory(stimulus_output_path)
    param_file_path = 'rtl/qracc_params.svh'

    # Setup log paths
    tb_file = f'../tb/{tb_path}/{tb_name}.sv'
    log_file = f'tests/logs/{tb_name}_{simulator}.log'
    logdir = os.path.dirname(log_file)
    os.makedirs(logdir,exist_ok=True)

    # Parameters are bound to the specific hardware configuration
    parameter_list = {
        "SRAM_ROWS": imc_core_size[0],
        "SRAM_COLS": imc_core_size[1],
        "QRACC_INPUT_BITS": 8,
        "QRACC_OUTPUT_BITS": 8,
        "GB_INT_IF_WIDTH": 32*8, # enough for a single bank
        "MODEL_MEM": 1, # This only works with the model memory :D
    }
    print(f'Parameter list: {parameter_list}')
    write_parameter_definition_file(parameter_list,param_file_path)

    u_code = get_single_node_marp_code(
        mnode_index = mnode_index,
        modelpath = modelpath,
        imc_core_size = imc_core_size,
        dwc_core_size = dwc_core_size
    )

    commands = u_code.compile()
    with open(f'{stimulus_output_path}/commands.txt', 'w') as f:
        for write in commands:
            f.write(write + '\n')
    u_code.write_files(stimulus_output_path)

    print(u_code)

    # Simulation
    run_simulation(simulator,{},package_list,tb_file,sim_args,rtl_file_list,log_file,run=True)

    # Post-simulation
    acc_result_flat = np.loadtxt("tb/qracc_top/outputs/hw_ofmap.txt", dtype=int)
    result_shape = np.loadtxt("tb/qracc_top/inputs/result_shape.txt", dtype=int)
    acc_result = acc_result_flat.reshape(*result_shape)

    rmse, snr = rmse_snr(u_code.reference_output, acc_result)
    save_scatter_fig(expected = u_code.reference_output,actual = acc_result, title = f"{u_code.matrix.shape} SNR {snr:.3f} dB",filename =  f"nx_singlenode_snr")
    print(acc_result.shape, u_code.reference_output.shape)
    # plot_diff_channels(acc_result - u_code.reference_output, tensor_format='NHWC', filename=f'nx_singlenode_channels')
    
    if mnode_index < 310:
        assert snr > 1, f'SNR: {snr}'
    else:
        print(f'The matmul nodes at the end have very low SNR due to a lack of variance in the output.')

    print(f'SNR: {snr:.3f} dB, RMSE: {rmse:.3f}')

    return

def test_qracc_with_all_onnx_single_node(
    simulator,
    modelpath = 'onnx_models/mbv2_cifar10_int8_binary.onnx',
    imc_core_size = (256, 256),
    dwc_core_size = 32,
):  
    '''
    Runs all nodes in the model and compares the output to the expected output.
    This tests single node runs in the entire model without packing, and produces an SNR list.
    '''  
    
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
    empty_directory(stimulus_output_path)
    param_file_path = 'rtl/qracc_params.svh'

    # Setup log paths
    tb_file = f'../tb/{tb_path}/{tb_name}.sv'
    log_file = f'tests/logs/{tb_name}_{simulator}.log'
    logdir = os.path.dirname(log_file)
    os.makedirs(logdir,exist_ok=True)

    # Parameters are bound to the specific hardware configuration
    parameter_list = {
        "SRAM_ROWS": imc_core_size[0],
        "SRAM_COLS": imc_core_size[1],
        "QRACC_INPUT_BITS": 8,
        "QRACC_OUTPUT_BITS": 8,
        "GB_INT_IF_WIDTH": 32*8, # enough for a single bank
        "NODUMP": 1,  # Disable dumping of VPD and VCD
        "NOTPLITZTRACK": 1, # Disable toeplitz tracking 
        "TRACK_STATISTICS": 1, # Enable tracking of statistics
    }
    print(f'Parameter list: {parameter_list}')
    write_parameter_definition_file(parameter_list,param_file_path)

    snrs = np.zeros(len(u_code.mapped_nodes))
    rmses = np.zeros(len(u_code.mapped_nodes))
    for mnode_index in range(len(u_code.mapped_nodes)):

        u_code = get_single_node_marp_code(
            mnode_index = mnode_index,
            modelpath = modelpath,
            imc_core_size = imc_core_size,
            dwc_core_size = dwc_core_size
        )

        commands = u_code.compile()
        with open(f'{stimulus_output_path}/commands.txt', 'w') as f:
            for write in commands:
                f.write(write + '\n')
        u_code.write_files(stimulus_output_path)

        print(u_code)

        # Simulation
        run_simulation(simulator,{},package_list,tb_file,sim_args,rtl_file_list,log_file,run=True)

        # Post-simulation
        acc_result_flat = np.loadtxt("tb/qracc_top/outputs/hw_ofmap.txt", dtype=int)
        result_shape = np.loadtxt("tb/qracc_top/inputs/result_shape.txt", dtype=int)
        acc_result = acc_result_flat.reshape(*result_shape)

        rmse, snr = rmse_snr(u_code.reference_output, acc_result)
        
        snrs[mnode_index] = snr
        rmses[mnode_index] = rmse

    # Save CSV of SNRs and RMSEs
    snr_df = pd.DataFrame({
        'node_id': range(len(snrs)),
        'snr': snrs,
        'rmse': rmses
    })
    snr_df.to_csv('snr_results.csv', index=False)

@pytest.mark.parametrize(
    "nx_model_and_name",
    [
        ("MBV2", onnx.load('onnx_models/mbv2_cifar10_int8_binary.onnx')),
        ("ResNet", onnx.load('hwacc_design_garage/onnx_models/ic_quantized_int8.onnx')),
        ("FCAE", onnx.load('hwacc_design_garage/onnx_models/ad_quantized_int8.onnx')),
        ("DSCNN", onnx.load('hwacc_design_garage/onnx_models/ks_quantized_int8.onnx')),
    ]
)
@pytest.mark.parametrize(
    "packer_and_name",
    [
        ("Dense",rectpack.newPacker(
            mode=rectpack.PackingMode.Offline,
            # bin_algo=rectpack.PackingBin.BBF, 
            rotation=False, 
            pack_algo=rectpack.MaxRectsBssf
        )),
        ("Naive",pu.NaiveRectpackPacker(256,256, rotation=False)),
        ("Tradeoff",rectpack.newPacker(
            mode=rectpack.PackingMode.Online,
            bin_algo=rectpack.PackingBin.BBF, 
            rotation=False, 
            pack_algo=rectpack.MaxRectsBssf
        )),
        ("Write Optimized",rectpack.newPacker(
            mode=rectpack.PackingMode.Online,
            bin_algo=rectpack.PackingBin.BNF, 
            rotation=False, 
            pack_algo=rectpack.MaxRectsBssf
        )),
    ]
)
def test_qracc_run_nx_model(
    simulator,
    nx_model_and_name,
    packer_and_name,
    imc_core_size = (256,256),
    dwc_core_size = 32,
    until = None,
    starting = 0,
):    
    model_name, nx_model = nx_model_and_name
    packername, packer = packer_and_name

    print('=' * 80)
    print(f'QrAcc Running model {model_name} with packer {packername}')

    print('=' * 80)

    np.random.seed(0)  # For reproducibility
    nx_model = onnx_utils.randomize_model_to_binary_weights(nx_model)
    
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
    hw_output_path = f'tb/{tb_path}/outputs'
    empty_directory(stimulus_output_path)
    empty_directory(hw_output_path)
    param_file_path = 'rtl/qracc_params.svh'

    # Setup log paths
    tb_file = f'../tb/{tb_path}/{tb_name}.sv'
    log_file = f'tests/logs/{tb_name}_{simulator}.log'
    logdir = os.path.dirname(log_file)
    os.makedirs(logdir,exist_ok=True)

    # Parameters are bound to the specific hardware configuration
    parameter_list = {
        "SRAM_ROWS": imc_core_size[0],
        "SRAM_COLS": imc_core_size[1],
        "QRACC_INPUT_BITS": 8,
        "QRACC_OUTPUT_BITS": 8,
        "GB_INT_IF_WIDTH": 32*8, # enough for a single bank
        "NODUMP": 1,  # Disable dumping of VPD and VCD
        "NOTPLITZTRACK": 1, # Disable toeplitz tracking 
        "NOIOFILES": 1, # Disable file I/O
        "SNOOP_OFMAP": 1, # Enable snooping of the output feature map
        "TRACK_STATISTICS": 1, # Enable tracking of statistics
        "MODEL_MEM": 1, # This only works with the model memory :D
    }
    print(f'Parameter list: {parameter_list}')
    write_parameter_definition_file(parameter_list,param_file_path)

    input_name = nx_model.graph.input[0].name
    input_shape = [d.dim_value for d in nx_model.graph.input[0].type.tensor_type.shape.dim]

    # If batch size > 1, set to 1
    if input_shape[0] > 1:
        nx_model.graph.input[0].type.tensor_type.shape.dim[0].dim_value = 1
        input_shape[0] = 1

    np.random.seed(0)
    print(input_shape)
    input_dict = {
        input_name: np.random.rand(*input_shape).astype(np.float32)
    }

    commands = traverse_and_compile_nx_graph(
        nx_model      = nx_model,
        input_dict    = input_dict,
        imc_core_size = imc_core_size,
        dwc_core_size = dwc_core_size,
        until         = until,
        starting      = starting,
        packer        = packer
    )  

    with open(f'{stimulus_output_path}/commands.txt', 'w') as f:
        for write in commands:
            f.write(write + '\n')

    # Simulation
    run_simulation(simulator,{},package_list,tb_file,sim_args,rtl_file_list,log_file,run=True)

    # Copy hw_output_path/qracc_statistics.csv to ../results/
    os.makedirs('results', exist_ok=True)
    stats_file = f'{hw_output_path}/qracc_statistics.csv'
    stats_dest_name = f'results/qracc_statistics_{model_name}_{packername}.csv'
    import shutil
    shutil.copy(stats_file, stats_dest_name)
        