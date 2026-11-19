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
NODE_NAME = '/features/features.0/features.0.0/Conv_quant'


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
