"""P7j: pre-shift (pre-ADC-range-shift) golden comparison for multibit weights.

Runs the Verilator simulation with +define+DEBUG to capture raw pre-shift
accumulator / mbl_value from seq_acc and ts_qracc, then compares against the
ONNXRuntime reference golden using least-squares scale fitting (same approach
as tests/_diag_scale_snr.py).  Asserts best-scale SNR > 8 dB and saves a PNG
scatter (gated by --figures, written to images/png/).

Runs ONLY inside the container (verilator + onnxruntime).  Not runnable on
hosts without verilator.
"""

import os
import re
import sys

import numpy as np
import onnx
import onnxruntime as ort
from onnx import helper
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
from .conftest import _normalize_cifar
from .test_marp_multibit_ref import (
    _find_node,
    _weight_initializer,
    _output_info,
    _shape_of,
    _run_with_output,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

MODEL_PATH = os.path.join(REPO_ROOT, 'onnx_models', 'mbv2_cifar10_int8.onnx')
IMAGE_PATH = os.path.join(REPO_ROOT, 'onnx_models', 'cifar10_test_bird4.jpg')
NODE_NAME = '/features/features.0/features.0.0/Conv_quant'


def same_b_reference(model_path, node_name, B, input_data=None):
    """ORt reference for conv node with weights reduced to B bits and re-scaled to int8.

    If ``input_data`` is given it is used directly as the model input; otherwise
    the CIFAR bird image is used (see _normalize_cifar).
    """
    model = onnx.load(model_path)
    node, init = _weight_initializer(model, node_name)
    w = onnx.numpy_helper.to_array(init)
    q = quant.quantize_int8_to_bits(w, B, signed=True)
    w_eff = np.clip(q * (2 ** (8 - B)), -128, 127).astype(np.int8)
    new_init = onnx.numpy_helper.from_array(w_eff, name=init.name)
    for idx, old in enumerate(model.graph.initializer):
        if old.name == init.name:
            model.graph.initializer[idx].CopyFrom(new_init)
            break
    input_name = model.graph.input[0].name
    if input_data is None:
        input_data = _normalize_cifar(IMAGE_PATH)
    return _run_with_output(model, node_name, input_name, input_data)


def parse_prestack_values(log_path):
    """Parse pre-shift raw values from the Verilator sim log.

    Returns (acc_pre, mbl_vals) where:
      acc_pre : list of dicts {n, i, accumulator, mac_data_o}
                accumulator  = pre-shift raw accumulator value (signed int)
                mac_data_o   = post-shift value (hex string -> int)
      mbl_vals : list of (j, mbl_value) from ts_qracc analog model
    """
    acc_pre = []
    mbl_vals = []
    with open(log_path) as f:
        for line in f:
            m = re.search(
                r'\[DBG seq_acc\] pre_shift n=(\d+) i=(\d+) accumulator\[(\d+)\]=(-?\d+) '
                r'mac_data_o\[(\d+)\]=([0-9a-fA-F]+)',
                line,
            )
            if m:
                acc_pre.append({
                    'n': int(m.group(1)),
                    'i': int(m.group(2)),
                    'accumulator': int(m.group(3)),
                    'mac_data_o': int(m.group(4), 16),
                })
                continue
            m = re.search(r'\[DBG ts_qracc\] mbl_value\[(\d+)\]=(-?\d+)', line)
            if m:
                mbl_vals.append((int(m.group(1)), int(m.group(2))))
    return acc_pre, mbl_vals


def snr_db(expected, actual):
    expected = np.asarray(expected, dtype=np.float64).ravel()
    actual = np.asarray(actual, dtype=np.float64).ravel()
    var_ref = float(np.var(expected))
    var_err = float(np.var(expected - actual))
    if var_err <= 0:
        return float("inf")
    return 10.0 * np.log10(var_ref / var_err)


@pytest.mark.needs_verilator
@pytest.mark.parametrize(
    "weight_bits",
    [2, 4, 8],
)
def test_marp_multibit_prestack(
    simulator,
    weight_bits,
    figures,
    modelpath='onnx_models/mbv2_cifar10_int8.onnx',
    imc_core_size=(256, 256),
    dwc_core_size=32,
):
    NODE_NAME = '/features/features.0/features.0.0/Conv_quant'

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

    tb_file = f'../tb/{tb_path}/{tb_name}.sv'
    log_file = f'tests/logs/{tb_name}_{simulator}.log'
    logdir = os.path.dirname(log_file)
    os.makedirs(logdir, exist_ok=True)

    parameter_list = {
        "SRAM_ROWS": imc_core_size[0],
        "SRAM_COLS": imc_core_size[1],
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

    # Enable +define+DEBUG (pre-shift dump blocks) and cap_file runtime plusarg.
    diag_utils.VERILATOR_RUN_PLUSARGS = [
        f'+cap_file=/workspaces/QrAccelerator/capdir/cap_B{weight_bits}.txt',
    ]
    os.environ['QRACC_DEBUG'] = '1'

    # Simulation
    run_simulation(simulator, {}, package_list, tb_file, diag_utils.sim_args,
                   rtl_file_list, log_file, run=True)

    # Parse pre-shift debug values from sim log
    acc_pre, mbl_vals = parse_prestack_values(log_file)
    print(f'B={weight_bits}: pre_shift accumulator events captured: {len(acc_pre)}')
    print(f'B={weight_bits}: mbl_value events captured: {len(mbl_vals)}')

    # ONNXRuntime golden using the SAME random input tensor as the RTL stimulus.
    # Convert uint8 input (0..255) to float32 NCHW normalized for the ONNX model.
    input_float = input_tensor.astype(np.float32) / 255.0
    mean = np.array((0.4914, 0.4822, 0.4465), dtype=np.float32).reshape(1, 3, 1, 1)
    std = np.array((0.2023, 0.1994, 0.2010), dtype=np.float32).reshape(1, 3, 1, 1)
    input_normalized = (input_float - mean) / std
    golden = same_b_reference(modelpath, NODE_NAME, weight_bits, input_data=input_normalized)

    # Scale-fit + SNR comparison (reuse _diag_scale_snr.py approach).
    # Scale is unknown between pre-shift raw values and the reference, so fit s.
    if len(acc_pre) > 0:
        hw = np.array([a['accumulator'] for a in acc_pre], dtype=np.float64)
        golden_flat = golden.ravel().astype(np.float64)
        n = min(len(hw), len(golden_flat))
        hw = hw[:n]
        golden_flat = golden_flat[:n]

        denom = float(np.sum(hw * hw))
        s = float(np.sum(hw * golden_flat) / denom) if denom > 0 else float("nan")
        scaled = s * hw

        best = snr_db(golden_flat, scaled)
        print(f'B={weight_bits}: best scale s={s:.6f}, best-scale SNR={best:.4f} dB')

        title = (f'Multibit B={weight_bits} pre-shift accumulator vs ONNX golden '
                 f'(s={s:.3f}, SNR={best:.2f} dB, n={n})')
        save_scatter_fig(expected=golden_flat, actual=scaled, title=title,
                         filename=f'multibit_prestack_B{weight_bits}', enabled=figures)

        assert best > 8, f'Pre-shift best-scale SNR: {best:.4f} dB (need > 8)'
    else:
        pytest.skip(
            "No pre_shift debug values found in sim log. "
            "Check that +define+DEBUG is active (QRACC_DEBUG=1)."
        )

    return
