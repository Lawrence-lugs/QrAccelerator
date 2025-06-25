import numpy as np
from tests.stim_lib.stimulus_gen import *
from tests.stim_lib.compile import *
from hwacctools.comp_graph import compute, cgraph, cnodes, core
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

    # Simulation
    run_simulation(simulator,{},package_list,tb_file,sim_args,rtl_file_list,log_file,run=True)

    # Post-simulation
    acc_result_flat = np.loadtxt("tb/qracc_top/outputs/hw_ofmap.txt", dtype=int)
    result_shape = np.loadtxt("tb/qracc_top/inputs/result_shape.txt", dtype=int)
    acc_result = acc_result_flat.reshape(*result_shape)

    rmse, snr = rmse_snr(u_code.reference_output, acc_result)
    save_scatter_fig(expected = u_code.reference_output,actual = acc_result, title = f"{u_code.matrix.shape} SNR {snr:.3f} dB",filename =  f"nx_singlenode_{mnode_index}_snr")
    print(acc_result.shape, u_code.reference_output.shape)
    # plot_diff_channels(acc_result - stimulus['result'], tensor_format='NHWC', filename=f'{test_name}_channels')
    assert snr > 1, f'SNR: {snr}'

    return