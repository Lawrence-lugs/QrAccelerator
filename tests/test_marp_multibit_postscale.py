"""Post-scaler (end-to-end) certification for the multibit analog path.

Unlike ``test_marp_multibit_prestack`` this compares the final int8 output
after ``output_scaler`` + output zero point against the ONNX node output for
the same input tensor.  It is the end-to-end gate for B=2/4/8.

The prestack test intentionally stops at ``qracc_mac_output``; this one starts
there and checks the part that the plan left open.
"""

import os

import numpy as np
import onnx
import pytest

marp = pytest.importorskip("qracc_marp")
from qracc_marp.compile.stimulus_gen import *  # noqa: F401,F403
from qracc_marp.compile.compile import *  # noqa: F401,F403
from qracc_marp.mapping import core
from qracc_marp.onnx_tools import onnx_utils

from .utils import *  # noqa: F401,F403
from . import utils as diag_utils

MODEL_PATH = 'onnx_models/mbv2_cifar10_int8.onnx'
MODEL_PATH_BINARY = 'onnx_models/mbv2_cifar10_int8_binary.onnx'
NODE_NAME = '/features/features.0/features.0.0/Conv_quant'


def test_python_postscale_binary_model_matches_onnx():
    """B=1 binary path: 0/1 weights, no 2x, no 2**(8-B) scale."""
    nx_model = onnx.load(MODEL_PATH_BINARY)
    u_nx_mapping = core.NxModelMapping(
        nx_model, imc_core_size=(256, 256), dwc_core_size=32)
    np.random.seed(0)
    input_dict = {
        'input.1': np.random.rand(1, 3, 32, 32).astype(np.float32)
    }
    node = next(mn for mn in u_nx_mapping.mapped_nodes if mn.name == NODE_NAME)
    input_shape = onnx_utils.get_intermediate_tensor_value(
        nx_model, nx_model.graph.node[node.node_id].input[0],
        input_dict=input_dict).shape
    input_tensor = np.random.randint(0, 256, input_shape).astype(np.uint8)

    expected = qlinearconv_onnx_reference(
        node, input_tensor, nx_model, weight_bits=1,
        weight_signed=False)[0]
    model = qlinearconv_post_scale_mac(
        node, input_tensor, weight_bits=1, weight_signed=False,
        adc_mode='none')
    rmse, snr = rmse_snr(expected, model)
    print(f'B=1 binary python-vs-ONNX SNR={snr:.3f} dB RMSE={rmse:.3f}')
    assert snr > 30, f'B=1 binary python golden SNR {snr:.3f} dB'


def test_python_postscale_depthwise_binary_matches_onnx():
    """Depthwise/WSAcc: raw kernel, no 2x, no B-bit plane reduction."""
    nx_model = onnx.load(MODEL_PATH_BINARY)
    u_nx_mapping = core.NxModelMapping(
        nx_model, imc_core_size=(256, 256), dwc_core_size=32)
    node = u_nx_mapping.mapped_nodes[1]
    assert node.depthwise, node.name
    np.random.seed(0)
    input_dict = {
        'input.1': np.random.rand(1, 3, 32, 32).astype(np.float32)
    }
    input_shape = onnx_utils.get_intermediate_tensor_value(
        nx_model, nx_model.graph.node[node.node_id].input[0],
        input_dict=input_dict).shape
    input_tensor = np.random.randint(0, 256, input_shape).astype(np.uint8)

    expected = qlinearconv_onnx_reference(
        node, input_tensor, nx_model, weight_bits=1,
        weight_signed=False)[0]
    model = qlinearconv_post_scale_mac(
        node, input_tensor, weight_bits=1, weight_signed=False,
        adc_mode='none')
    rmse, snr = rmse_snr(expected, model)
    print(f'depthwise binary python-vs-ONNX SNR={snr:.3f} dB RMSE={rmse:.3f}')
    assert snr > 30, f'depthwise binary python golden SNR {snr:.3f} dB'


def test_python_postscale_matmul_binary_matches_onnx():
    """Final QLinearMatMul is mapped as a 1x1 conv; check it too."""
    nx_model = onnx.load(MODEL_PATH_BINARY)
    u_nx_mapping = core.NxModelMapping(
        nx_model, imc_core_size=(256, 256), dwc_core_size=32)
    node = u_nx_mapping.mapped_nodes[310]
    np.random.seed(0)
    input_dict = {
        'input.1': np.random.rand(1, 3, 32, 32).astype(np.float32)
    }
    input_shape = onnx_utils.get_intermediate_tensor_value(
        nx_model, nx_model.graph.node[node.node_id].input[0],
        input_dict=input_dict).shape
    input_tensor = np.random.randint(0, 256, input_shape).astype(np.uint8)

    expected = qlinearconv_onnx_reference(
        node, input_tensor, nx_model, weight_bits=1,
        weight_signed=False)[0]
    model = qlinearconv_post_scale_mac(
        node, input_tensor, weight_bits=1, weight_signed=False,
        adc_mode='none')
    rmse, snr = rmse_snr(expected, model)
    max_abs = int(np.max(np.abs(expected.astype(int) - model.astype(int))))
    print(f'matmul binary python-vs-ONNX max|diff|={max_abs} RMSE={rmse:.3f}')
    # The final matmul output has almost no variance (all codes near y_zp);
    # SNR is meaningless here.  Require the exact integer pipeline instead.
    assert max_abs <= 1, f'matmul binary max|diff| {max_abs}'


@pytest.mark.parametrize(
    "model_path,weight_bits,weight_signed",
    [
        (MODEL_PATH_BINARY, 1, False),
        (MODEL_PATH, 2, True),
        (MODEL_PATH, 4, True),
        (MODEL_PATH, 8, True),
    ],
)
def test_adc_config_uses_bank_full_scale(model_path, weight_bits, weight_signed):
    """The ADC full scale is numRows; s is the only range selection."""
    nx_model = onnx.load(model_path)
    u_nx_mapping = core.NxModelMapping(
        nx_model, imc_core_size=(256, 256), dwc_core_size=32)
    node = next(mn for mn in u_nx_mapping.mapped_nodes if mn.name == NODE_NAME)
    np.random.seed(0)
    input_dict = {
        'input.1': np.random.rand(1, 3, 32, 32).astype(np.float32)
    }
    input_shape = onnx_utils.get_intermediate_tensor_value(
        nx_model, nx_model.graph.node[node.node_id].input[0],
        input_dict=input_dict).shape
    input_tensor = np.random.randint(0, 256, input_shape).astype(np.uint8)
    u_code = QrAccNodeCode(
        node, u_nx_mapping.mapped_bins[node.bin_id], input_tensor,
        imc_core_size=(256, 256), ws_core_size=32,
        weight_bits=weight_bits, weight_signed=weight_signed,
        nx_model=nx_model)
    cfg = u_code.config()
    assert u_code.adc_config['fs_counts'] == 256.0
    assert 0 <= cfg['adc_ref_range_shifts'] <= 8
    assert u_code.adc_config['lsb_counts'] == 256.0 / (
        2 ** (cfg['adc_ref_range_shifts'] + 3))


@pytest.mark.parametrize("weight_bits", [2, 4, 8])
def test_python_postscale_model_matches_onnx(weight_bits):
    """The Python golden must agree with ONNX before it judges RTL."""
    nx_model = onnx.load(MODEL_PATH)
    u_nx_mapping = core.NxModelMapping(
        nx_model, imc_core_size=(256, 256), dwc_core_size=32)
    np.random.seed(0)
    input_dict = {
        'input.1': np.random.rand(1, 3, 32, 32).astype(np.float32)
    }
    node = next(mn for mn in u_nx_mapping.mapped_nodes if mn.name == NODE_NAME)
    input_shape = onnx_utils.get_intermediate_tensor_value(
        nx_model, nx_model.graph.node[node.node_id].input[0],
        input_dict=input_dict).shape
    input_tensor = np.random.randint(0, 256, input_shape).astype(np.uint8)

    expected = qlinearconv_onnx_reference(
        node, input_tensor, nx_model, weight_bits=weight_bits)[0]
    model = qlinearconv_post_scale_mac(
        node, input_tensor, weight_bits=weight_bits, adc_mode='none')
    rmse, snr = rmse_snr(expected, model)
    print(f'B={weight_bits} python-vs-ONNX SNR={snr:.3f} dB RMSE={rmse:.3f}')
    assert snr > 30, f'B={weight_bits} python golden SNR {snr:.3f} dB'


def _run_binary_node(simulator, nx_model, node, ifmap, tag, weight_bits=1):
    """Run one node through the RTL and return (u_code, hw_output)."""
    bin = None if node.depthwise else None
    # The binary model's mapped bin is only needed for non-depthwise nodes.
    if not node.depthwise:
        mapping = core.NxModelMapping(
            nx_model, imc_core_size=(256, 256), dwc_core_size=32)
        bin = mapping.mapped_bins[node.bin_id]

    u_code = QrAccNodeCode(
        mapped_node=node,
        mapped_bin=bin,
        ifmap=ifmap,
        imc_core_size=(256, 256),
        ws_core_size=32,
        weight_bits=weight_bits,
        weight_signed=weight_bits > 1,
        nx_model=nx_model,
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
    stimulus_output_path = 'tb/qracc_top/inputs'
    empty_directory(stimulus_output_path)
    os.makedirs('tb/qracc_top/outputs', exist_ok=True)
    write_parameter_definition_file({
        "SRAM_ROWS": 256,
        "SRAM_COLS": 256,
        "QRACC_INPUT_BITS": 8,
        "QRACC_OUTPUT_BITS": 8,
        "GB_INT_IF_WIDTH": 32 * 8,
        "MODEL_MEM": 1,
    }, 'rtl/qracc_params.svh')

    with open(f'{stimulus_output_path}/commands.txt', 'w') as f:
        for write in u_code.compile():
            f.write(write + '\n')
    u_code.write_files(stimulus_output_path)

    diag_utils.VERILATOR_RUN_PLUSARGS = []
    log_file = f'tests/logs/tb_qracc_top_{simulator}_{tag}.log'
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    run_simulation(
        simulator, {}, package_list, '../tb/qracc_top/tb_qracc_top.sv',
        diag_utils.sim_args, rtl_file_list, log_file, run=True)

    flat = np.loadtxt('tb/qracc_top/outputs/hw_ofmap.txt', dtype=int)
    shape = np.loadtxt('tb/qracc_top/inputs/result_shape.txt', dtype=int)
    return u_code, flat.reshape(*shape)


@pytest.mark.needs_verilator
def test_marp_binary_chain_conv_depthwise(simulator):
    """First true e2e chain: conv output feeds the next depthwise node."""
    nx_model = onnx.load(MODEL_PATH_BINARY)
    mapping = core.NxModelMapping(
        nx_model, imc_core_size=(256, 256), dwc_core_size=32)
    node0, node1 = mapping.mapped_nodes[0], mapping.mapped_nodes[1]
    assert node1.depthwise, node1.name

    np.random.seed(0)
    input_dict = {
        'input.1': np.random.rand(1, 3, 32, 32).astype(np.float32)
    }
    input0 = np.random.randint(
        0, 256, input_dict['input.1'].shape).astype(np.uint8)
    # Use the quantized model input shape (NCHW).
    input0 = onnx_utils.get_intermediate_tensor_value(
        nx_model, nx_model.graph.node[node0.node_id].input[0],
        input_dict=input_dict).astype(np.uint8)
    input0 = np.random.randint(0, 256, input0.shape).astype(np.uint8)

    u0, out0 = _run_binary_node(simulator, nx_model, node0, input0, 'chain0')
    exp0 = qlinearconv_onnx_reference(
        node0, input0, nx_model, weight_bits=1, weight_signed=False)
    _, snr0 = rmse_snr(exp0, out0)
    print(f'chain stage 0 conv SNR={snr0:.3f} dB')
    assert snr0 > 8, f'stage0 SNR {snr0:.3f}'

    # Feed the RTL output of stage 0 into stage 1 and compare stage 1 with
    # ONNX driven by that same (hardware) input.
    # hw_ofmap is NHWC; QrAccNodeCode expects NCHW.
    input1 = out0.transpose(0, 3, 1, 2).astype(np.uint8)
    u1, out1 = _run_binary_node(simulator, nx_model, node1, input1, 'chain1')
    exp1 = qlinearconv_onnx_reference(
        node1, input1, nx_model, weight_bits=1, weight_signed=False)
    _, snr1 = rmse_snr(exp1, out1)
    print(f'chain stage 1 depthwise SNR={snr1:.3f} dB')
    assert snr1 > 8, f'stage1 SNR {snr1:.3f}'


@pytest.mark.needs_verilator
@pytest.mark.parametrize("n_nodes", [3, 4, 5, 7])
def test_marp_e2e_multibit_slice(simulator, n_nodes):
    """True e2e: real ONNX activations, per-node B, contiguous slice."""
    nx_model = onnx.load(MODEL_PATH)
    mapping = core.NxModelMapping(
        nx_model, imc_core_size=(256, 256), dwc_core_size=32)
    last_node = mapping.mapped_nodes[n_nodes - 1]
    assert mapping.mapped_nodes[1].depthwise

    np.random.seed(0)
    input_dict = {
        'input.1': np.random.rand(1, 3, 32, 32).astype(np.float32)
    }
    commands = traverse_and_compile_nx_graph(
        nx_model, input_dict, imc_core_size=(256, 256),
        dwc_core_size=32, until=last_node.node_id + 1, weight_bits=8,
        real_activations=True,
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
    stimulus_output_path = 'tb/qracc_top/inputs'
    empty_directory(stimulus_output_path)
    os.makedirs('tb/qracc_top/outputs', exist_ok=True)
    write_parameter_definition_file({
        "SRAM_ROWS": 256,
        "SRAM_COLS": 256,
        "QRACC_INPUT_BITS": 8,
        "QRACC_OUTPUT_BITS": 8,
        "GB_INT_IF_WIDTH": 32 * 8,
        "MODEL_MEM": 1,
        "NOIOFILES": 1,
    }, 'rtl/qracc_params.svh')
    with open(f'{stimulus_output_path}/commands.txt', 'w') as f:
        for write in commands:
            f.write(write + '\n')

    diag_utils.VERILATOR_RUN_PLUSARGS = []
    # Do not let a previous run's readout mask a node that never wrote.
    try:
        os.remove('tb/qracc_top/outputs/hw_ofmap.txt')
    except FileNotFoundError:
        pass
    log_file = f'tests/logs/tb_qracc_top_{simulator}_e2e3.log'
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    sim_args = {k: list(v) for k, v in diag_utils.sim_args.items()}
    if n_nodes == 7:
        for args in sim_args.values():
            args.append('+define+ACTMEM_DEBUG')
    run_simulation(
        simulator, {}, package_list, '../tb/qracc_top/tb_qracc_top.sv',
        sim_args, rtl_file_list, log_file, run=True)

    expected_nchw = onnx_utils.get_intermediate_tensor_value(
        nx_model, last_node.nx_node.output[0], input_dict=input_dict)
    expected = expected_nchw.transpose(0, 2, 3, 1)
    flat = np.loadtxt('tb/qracc_top/outputs/hw_ofmap.txt', dtype=int)
    assert flat.size == expected.size, (flat.size, expected.size)
    actual = flat.reshape(expected.shape)
    rmse, snr = rmse_snr(expected, actual)
    print(f'e2e {n_nodes}-node B=8 SNR={snr:.3f} dB RMSE={rmse:.3f}')
    assert snr > 8, f'e2e {n_nodes}-node SNR {snr:.3f} dB'


@pytest.mark.needs_verilator
@pytest.mark.parametrize("weight_bits", [2, 4, 8])
def test_marp_multibit_postscale(simulator, weight_bits, figures):
    nx_model = onnx.load(MODEL_PATH)
    u_nx_mapping = core.NxModelMapping(
        nx_model, imc_core_size=(256, 256), dwc_core_size=32)

    np.random.seed(0)
    input_dict = {
        'input.1': np.random.rand(1, 3, 32, 32).astype(np.float32)
    }

    mnode_index = None
    for i, mn in enumerate(u_nx_mapping.mapped_nodes):
        if mn.name == NODE_NAME:
            mnode_index = i
            break
    assert mnode_index is not None, f'node {NODE_NAME!r} not found'

    node = u_nx_mapping.mapped_nodes[mnode_index]
    bin = u_nx_mapping.mapped_bins[node.bin_id] if not node.depthwise else None
    input_tensor_shape = onnx_utils.get_intermediate_tensor_value(
        nx_model, nx_model.graph.node[node.node_id].input[0],
        input_dict=input_dict).shape
    input_tensor = np.random.randint(0, 256, input_tensor_shape).astype(np.uint8)

    u_code = QrAccNodeCode(
        mapped_node=node,
        mapped_bin=bin,
        ifmap=input_tensor,
        imc_core_size=(256, 256),
        ws_core_size=32,
        weight_bits=weight_bits,
        weight_signed=True,
        nx_model=nx_model,
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
    tb_path = 'qracc_top'
    stimulus_output_path = f'tb/{tb_path}/inputs'
    empty_directory(stimulus_output_path)
    os.makedirs(f'tb/{tb_path}/outputs', exist_ok=True)
    param_file_path = 'rtl/qracc_params.svh'

    parameter_list = {
        "SRAM_ROWS": 256,
        "SRAM_COLS": 256,
        "QRACC_INPUT_BITS": 8,
        "QRACC_OUTPUT_BITS": 8,
        "GB_INT_IF_WIDTH": 32 * 8,
        "MODEL_MEM": 1,
    }
    write_parameter_definition_file(parameter_list, param_file_path)

    commands = u_code.compile()
    with open(f'{stimulus_output_path}/commands.txt', 'w') as f:
        for write in commands:
            f.write(write + '\n')
    u_code.write_files(stimulus_output_path)

    tb_file = f'../tb/{tb_path}/tb_qracc_top.sv'
    log_file = f'tests/logs/tb_qracc_top_{simulator}.log'
    os.makedirs(os.path.dirname(log_file), exist_ok=True)

    diag_utils.VERILATOR_RUN_PLUSARGS = ['+qr_dbg_mac']
    run_simulation(simulator, {}, package_list, tb_file, diag_utils.sim_args,
                   rtl_file_list, log_file, run=True)

    actual_flat = np.loadtxt("tb/qracc_top/outputs/hw_ofmap.txt", dtype=int)
    result_shape = np.loadtxt("tb/qracc_top/inputs/result_shape.txt", dtype=int)
    actual = actual_flat.reshape(*result_shape)
    expected = qlinearconv_onnx_reference(
        node, input_tensor, nx_model, weight_bits=weight_bits)

    assert actual.shape == expected.shape, (actual.shape, expected.shape)
    rmse, snr = rmse_snr(expected, actual)
    print(f'B={weight_bits} post-scaler SNR={snr:.3f} dB RMSE={rmse:.3f}')

    if figures:
        save_scatter_fig(
            expected=expected.ravel(), actual=actual.ravel(),
            title=f'Multibit B={weight_bits} post-scaler SNR={snr:.2f} dB',
            filename=f'multibit_postscale_B{weight_bits}',
            enabled=True,
        )

    # The analog path is approximate; 8 dB is the existing end-to-end gate.
    assert snr > 8, f'B={weight_bits} post-scaler SNR {snr:.3f} dB'
