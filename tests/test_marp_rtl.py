import numpy as np
import pytest
marp = pytest.importorskip("qracc_marp")
from qracc_marp.compile.stimulus_gen import *
from qracc_marp.compile.compile import *
from qracc_marp.compile import compute
from qracc_marp.mapping import core
from qracc_marp.mapping import packer_utils as pu
from qracc_marp.onnx_tools import onnx_splitter
from qracc_marp.onnx_tools import onnx_utils
import qracc_marp.quantization.quant as quant
from .utils import *
from . import utils as diag_utils

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

@pytest.mark.needs_verilator
@pytest.mark.parametrize(
    "mnode_index",
    [0, 1, 2, 3, 4, 308, 309, 310]
)
def test_qracc_with_onnx_single_node(
    simulator,
    mnode_index,
    figures,
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
        '../rtl/bipolar_bias_sub.sv',
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
    os.makedirs(f'tb/{tb_path}/outputs', exist_ok=True)
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
        # uint8 activations are magnitudes: all 8 bits are data.
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
    save_scatter_fig(expected = u_code.reference_output,actual = acc_result, title = f"{u_code.matrix.shape} SNR {snr:.3f} dB",filename =  f"nx_singlenode_snr", enabled=figures)
    print(acc_result.shape, u_code.reference_output.shape)
    # plot_diff_channels(acc_result - u_code.reference_output, tensor_format='NHWC', filename=f'nx_singlenode_channels')
    
    if mnode_index < 310:
        assert snr > 1, f'SNR: {snr}'
    else:
        print(f'The matmul nodes at the end have very low SNR due to a lack of variance in the output.')

    print(f'SNR: {snr:.3f} dB, RMSE: {rmse:.3f}')

    return


@pytest.mark.needs_verilator
@pytest.mark.parametrize(
    "weight_bits",
    [2, 4, 8],
)
def test_marp_multibit_node_int8(
    simulator,
    weight_bits,
    modelpath='onnx_models/mbv2_cifar10_int8.onnx',
    imc_core_size=(256, 256),
    dwc_core_size=32,
):
    import os, time
    from pathlib import Path
    NODE_NAME = '/features/features.0/features.0.0/Conv_quant'
    REPO_ROOT = Path(__file__).resolve().parents[1]
    REF_DIR = REPO_ROOT / 'tests' / 'multibit_ref'

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

    mnode_index = None
    for i, mn in enumerate(u_nx_mapping.mapped_nodes):
        if mn.name == NODE_NAME:
            mnode_index = i
            break
    assert mnode_index is not None, f'node {NODE_NAME!r} not found in mapped nodes'

    node = u_nx_mapping.mapped_nodes[mnode_index]
    node_id = node.node_id
    bin = u_nx_mapping.mapped_bins[node.bin_id] if not node.depthwise else None

    input_tensor_shape = onnx_utils.get_intermediate_tensor_value(
        nx_model, nx_model.graph.node[node_id].input[0], input_dict=input_dict).shape
    input_tensor = np.random.randint(0, 256, input_tensor_shape).astype(np.uint8)

    u_code = QrAccNodeCode(
        mapped_node=node,
        mapped_bin=bin,
        ifmap=input_tensor,
        imc_core_size=imc_core_size,
        ws_core_size=dwc_core_size,
        weight_bits=weight_bits,
        weight_signed=True,
        nx_model=nx_model
    )

    package_list = ['../rtl/qracc_params.svh', '../rtl/qracc_pkg.svh']
    rtl_file_list = [
        '../rtl/activation_buffer/piso_write_queue.sv',
        '../rtl/activation_buffer/mm_output_aligner.sv',
        '../rtl/wsacc/wsacc_pe_cluster.sv',
        '../rtl/wsacc/wsacc_pe.sv',
        '../rtl/qr_acc_wrapper.sv',
        '../rtl/bipolar_bias_sub.sv',
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
    os.makedirs(f'tb/{tb_path}/outputs', exist_ok=True)
    param_file_path = 'rtl/qracc_params.svh'

    # Setup log paths
    tb_file = f'../tb/{tb_path}/{tb_name}.sv'
    log_file = f'tests/logs/{tb_name}_{simulator}.log'
    logdir = os.path.dirname(log_file)
    os.makedirs(logdir, exist_ok=True)

    # Parameters are bound to the specific hardware configuration
    parameter_list = {
        "SRAM_ROWS": imc_core_size[0],
        "SRAM_COLS": imc_core_size[1],
        # uint8 activations are magnitudes: all 8 bits are data.
        "QRACC_INPUT_BITS": 8,
        "QRACC_OUTPUT_BITS": 8,
        "GB_INT_IF_WIDTH": 32 * 8,  # enough for a single bank
        "MODEL_MEM": 1,  # This only works with the model memory :D
    }
    print(f'Parameter list: {parameter_list}')
    write_parameter_definition_file(parameter_list, param_file_path)

    commands = u_code.compile()
    with open(f'{stimulus_output_path}/commands.txt', 'w') as f:
        for write in commands:
            f.write(write + '\n')
    u_code.write_files(stimulus_output_path)

    print(u_code)

    # Simulation
    capdir = REPO_ROOT / 'capdir'
    capdir.mkdir(exist_ok=True)
    diag_utils.VERILATOR_RUN_PLUSARGS = [
        f'+cap_file={capdir / f"cap_B{weight_bits}.txt"}',
    ]
    run_simulation(simulator, {}, package_list, tb_file, sim_args, rtl_file_list, log_file, run=True)

    acc_result_flat = np.loadtxt("tb/qracc_top/outputs/hw_ofmap.txt", dtype=int)
    result_shape = np.loadtxt("tb/qracc_top/inputs/result_shape.txt", dtype=int)
    acc_result = acc_result_flat.reshape(*result_shape)

    safe = NODE_NAME.lstrip('/').replace('/', '_')
    ref_path = os.path.join(REF_DIR, f'{safe}_B{weight_bits}.npy')
    ref = np.load(ref_path).transpose((0, 2, 3, 1))

    rmse, snr = rmse_snr(ref, acc_result)
    print(f'SNR B={weight_bits}: {snr:.3f} dB, RMSE: {rmse:.3f}')
    assert snr > 8, f'SNR: {snr}'

    return


@pytest.mark.heavy
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
        '../rtl/bipolar_bias_sub.sv',
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
    os.makedirs(f'tb/{tb_path}/outputs', exist_ok=True)
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
        # uint8 activations are magnitudes: all 8 bits are data.
        "QRACC_INPUT_BITS": 8,
        "QRACC_OUTPUT_BITS": 8,
        "GB_INT_IF_WIDTH": 32*8, # enough for a single bank
        "NODUMP": 1,  # Disable dumping of VPD and VCD
        "NOTPLITZTRACK": 1, # Disable toeplitz tracking 
        "TRACK_STATISTICS": 1, # Enable tracking of statistics
    }
    print(f'Parameter list: {parameter_list}')
    write_parameter_definition_file(parameter_list,param_file_path)

    # Determine node count up-front (avoids UnboundLocalError: u_code used
    # before assignment in the loop below).
    _probe_model = onnx.load(modelpath)
    _probe_mapping = core.NxModelMapping(
        _probe_model,
        imc_core_size=imc_core_size,
        dwc_core_size=dwc_core_size
    )
    num_nodes = len(_probe_mapping.mapped_nodes)
    snrs = np.zeros(num_nodes)
    rmses = np.zeros(num_nodes)
    for mnode_index in range(num_nodes):

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
    snr_df.to_csv('sims/snr_results.csv', index=False)


def make_packers():
    """Return a fresh dict of rectpack packers (one instance per name).

    Packer objects are stateful, so a new instance is created on every call
    to avoid cross-model contamination.
    """
    import rectpack
    from qracc_marp.mapping import packer_utils as pu
    return {
        "Dense": rectpack.newPacker(
            mode=rectpack.PackingMode.Offline,
            rotation=False,
            pack_algo=rectpack.MaxRectsBssf
        ),
        "Naive": pu.NaiveRectpackPacker(256, 256, rotation=False),
        "Tradeoff": rectpack.newPacker(
            mode=rectpack.PackingMode.Online,
            bin_algo=rectpack.PackingBin.BBF,
            rotation=False,
            pack_algo=rectpack.MaxRectsBssf
        ),
        "Write Optimized": rectpack.newPacker(
            mode=rectpack.PackingMode.Online,
            bin_algo=rectpack.PackingBin.BNF,
            rotation=False,
            pack_algo=rectpack.MaxRectsBssf
        ),
    }


@pytest.mark.heavy
@pytest.mark.parametrize(
    "nx_model_and_name",
    [
        ("MBV2", 'onnx_models/mbv2_cifar10_int8_binary.onnx'),
        ("ResNet", 'artifacts/onnx_models/ic_quantized_int8.onnx'),
        ("FCAE", 'artifacts/onnx_models/ad_quantized_int8.onnx'),
        ("DSCNN", 'artifacts/onnx_models/ks_quantized_int8.onnx'),
    ]
)
@pytest.mark.parametrize(
    "packer_name",
    [
        "Dense",
        "Naive",
        "Tradeoff",
        "Write Optimized",
    ]
)
def test_qracc_run_nx_model(
    simulator,
    nx_model_and_name,
    packer_name,
    imc_core_size = (256,256),
    dwc_core_size = 32,
    until = None,
    starting = 0,
):    
    model_name, nx_model_path = nx_model_and_name

    import pathlib
    if not pathlib.Path(nx_model_path).exists():
        pytest.skip(f"ONNX model {nx_model_path} not found; generate it in the MARP container and place it under artifacts/onnx_models/")
    nx_model = onnx.load(nx_model_path)

    # Fresh packer per model invocation (module-level packer objects were
    # stateful and reused across models, which is a bug).
    packers = make_packers()
    packer = packers[packer_name]

    print('=' * 80)
    print(f'QrAcc Running model {model_name} with packer {packer_name}')

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
        '../rtl/bipolar_bias_sub.sv',
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
        # uint8 activations are magnitudes: all 8 bits are data.
        "QRACC_INPUT_BITS": 8,
        "QRACC_OUTPUT_BITS": 8,
        "GB_INT_IF_WIDTH": 32*8, # enough for a single bank
        "NODUMP": 1,  # Disable dumping of VPD and VCD
        "NOIOFILES": 1, # Disable file I/O
        "TRACK_STATISTICS": 1, # Enable tracking of statistics
        "MODEL_MEM": 1, # This only works with the model memory :D
    }
    if simulator != "verilator": # These debug features cause issues with verilator
        parameter_list["NOTPLITZTRACK"] = 1
        parameter_list["SNOOP_OFMAP"] = 1

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
    stats_dest_name = f'results/qracc_statistics_{model_name}_{packer_name}.csv'
    import shutil
    shutil.copy(stats_file, stats_dest_name)
        

