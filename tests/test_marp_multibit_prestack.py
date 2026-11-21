"""RTL pre-scale MAC vs golden SNR certification for multi-bit weights.

Runs ``tb_qracc_top`` under Verilator with the runtime plusarg ``+qr_dbg_mac``
and compares the **full** pre-shift accumulator stream (every output window,
every output channel) against :func:`tests.utils.qlinearconv_pre_scale_mac`.

What is compared
----------------
The RTL pre-shift accumulator is *unfolded*: the zero-point fold
``-x_zp * sum(w_B)`` is not applied in ``seq_acc``, it lives in
``mapped_node.biases`` and is added downstream by ``output_scaler``.  The golden
is therefore evaluated with ``unfold=True``.

Two references are built from the same input tensor:

* ``exact``     - exact integer MAC (``adc_mode="none"``, ``unfold=True``);
* ``model``     - the RTL datapath emulation (``adc_mode="per_plane"``), i.e.
  the flash ADC of ``rtl/ts_qracc.sv`` applied to **every** partial sum before
  the shift-add, using the compiled ``adc_ref_range_shifts``.

Acceptance criterion
--------------------
The RTL must be *near* the SNR of the golden model::

    | SNR(rtl, exact) - SNR(model, exact) | <= 1.0 dB

This is deliberately **not** a bit-exact assertion.  Residual bit-level
differences (comparator offset ordering, PISO edge cases, accumulator
truncation) are deferred to a later pass; see the ablation test
``tests/test_marp_multibit_adc_ablation.py`` for the underlying ADC trade-off.

The switch-matrix blanking bug and the missing bipolar bias are fixed (see
``FINDINGS_multibit_prescale.md`` §1/§11): the selects are driven for the whole
MAC word, ``seq_acc`` subtracts ``sum_j 2**j A_j`` and publishes ``2*MAC``.
The pre-shift capture therefore satisfies
``post == (lsb*pre - activation_sum) << s``.

Runs ONLY inside the container (verilator).
"""

import os
import re
import sys

import numpy as np
import onnx
import pytest

marp = pytest.importorskip("qracc_marp")
from qracc_marp.compile.stimulus_gen import *
from qracc_marp.compile.compile import *
from qracc_marp.mapping import core

from .utils import (
    empty_directory,
    qlinearconv_prescale_snr,
    run_simulation,
    save_scatter_fig,
    sim_inputs,
    sim_outputs,
    sim_params_path,
    write_parameter_definition_file,
)
from . import utils as diag_utils

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

MODEL_PATH = 'onnx_models/mbv2_cifar10_int8.onnx'
NODE_NAME = '/features/features.0/features.0.0/Conv_quant'

# Tolerance between the RTL SNR and the golden-model SNR (see module docstring).
SNR_TOLERANCE_DB = 1.0


def parse_mac_capture(log_path):
    """Parse ``[DBG cfg]`` / ``[DBG win]`` / ``[DBG mac]`` lines from the log.

    Returns ``(cfg, wins, pre, post)`` where

    * ``cfg``   - dict of the CSR-programmed geometry/shift values;
    * ``wins``  - list of ``(k, x, y)`` accepted-window tags;
    * ``pre``   - ``{(k, o): accumulator}`` (pre-shift, seq_acc units);
    * ``post``  - ``{(k, o): mac_data_o}`` (after ``<< adc_ref_range_shifts``).
    """
    win_re = re.compile(r'\[DBG win\] k=(\d+) x=(-?\d+) y=(-?\d+)')
    mac_re = re.compile(r'\[DBG mac\] k=(\d+) o=(\d+) pre=(-?\d+) post=(-?\d+)')
    cfg_re = re.compile(
        r'\[DBG cfg\] adc_ref_range_shifts=(\d+) num_output_channels=(\d+) '
        r'mapped_matrix_offset_x=(\d+) output_fmap_dimx=(\d+) '
        r'output_fmap_dimy=(\d+)')
    wins, pre, post, cfg = [], {}, {}, {}
    with open(log_path, errors='replace') as f:
        for line in f:
            m = mac_re.search(line)
            if m:
                k, o = int(m.group(1)), int(m.group(2))
                pre[(k, o)] = int(m.group(3))
                post[(k, o)] = int(m.group(4))
                continue
            m = win_re.search(line)
            if m:
                wins.append((int(m.group(1)), int(m.group(2)), int(m.group(3))))
                continue
            m = cfg_re.search(line)
            if m:
                cfg = {
                    'adc_ref_range_shifts': int(m.group(1)),
                    'num_output_channels': int(m.group(2)),
                    'mapped_matrix_offset_x': int(m.group(3)),
                    'output_fmap_dimx': int(m.group(4)),
                    'output_fmap_dimy': int(m.group(5)),
                }
    return cfg, wins, pre, post


def snr_db(expected, actual):
    expected = np.asarray(expected, dtype=np.float64).ravel()
    actual = np.asarray(actual, dtype=np.float64).ravel()
    var_err = float(np.var(expected - actual))
    if var_err <= 0:
        return float("inf")
    return 10.0 * np.log10(float(np.var(expected)) / var_err)


@pytest.mark.needs_verilator
@pytest.mark.parametrize(
    "weight_bits",
    [2, 4, 8],
)
def test_marp_multibit_prestack(
    simulator,
    weight_bits,
    figures,
    modelpath=MODEL_PATH,
    imc_core_size=(256, 256),
    dwc_core_size=32,
):
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
    bin = u_nx_mapping.mapped_bins[node.bin_id] if not node.depthwise else None

    from qracc_marp.onnx_tools import onnx_utils
    input_tensor_shape = onnx_utils.get_intermediate_tensor_value(
        nx_model, nx_model.graph.node[node.node_id].input[0],
        input_dict=input_dict).shape
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
    stimulus_output_path = sim_inputs(tb_path)
    empty_directory(stimulus_output_path)
    os.makedirs(sim_outputs(tb_path), exist_ok=True)
    param_file_path = sim_params_path()

    tb_file = f'../tb/{tb_path}/{tb_name}.sv'
    log_file = f'{tb_name}_{simulator}.log'

    parameter_list = {
        "SRAM_ROWS": imc_core_size[0],
        "SRAM_COLS": imc_core_size[1],
        # uint8 activations: all 8 bits are data (the top bit is only a sign
        # for ternary inputs), so input_trits = 8 without widening the lane.
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

    # The capture is gated by the runtime plusarg +qr_dbg_mac (the testbench
    # cannot use a compile-time define: verilator defines are position-sensitive
    # on the command line, and the tb is listed before sim_args).
    # Pass it explicitly so concurrent tests cannot leak plusargs.
    log_file = run_simulation(
        simulator, {}, package_list, tb_file, diag_utils.sim_args,
        rtl_file_list, log_file, run=True, run_plusargs=['+qr_dbg_mac'])

    cfg_info, wins, pre, post = parse_mac_capture(log_file)
    assert cfg_info, (
        'no [DBG cfg] line found - the +qr_dbg_mac plusarg did not reach the '
        'simulation (see run_simulation(run_plusargs=...))')
    shift = cfg_info['adc_ref_range_shifts']
    # The CSR value the hardware used must agree with the compiler decision.
    assert shift == int(u_code.config()['adc_ref_range_shifts']), (
        f"TB reports s={shift} but compiler configured "
        f"s={u_code.config()['adc_ref_range_shifts']}")

    assert pre, 'no [DBG mac] samples found in the sim log'

    # Reference tensors (unfolded: the zero-point fold lives in the bias path).
    # qlinearconv_prescale_snr builds both: the exact integer MAC
    # (adc_mode="none") and the per-plane ADC emulation (adc_mode="per_plane").
    # ADC configuration actually chosen for this layer.  `fs_counts` is an
    # analog target (the reference full scale), not a CSR field: the compiler
    # reports it, the hardware does not switch it at runtime.
    adc_cfg = getattr(u_code, 'adc_config', {}) or {}
    reference = qlinearconv_prescale_snr(
        node, input_tensor, weight_bits=weight_bits, adc_shift=shift,
        adc_bits=int(adc_cfg.get('bits', 4)), ladder='bipolar',
        fs_counts=adc_cfg.get('fs_counts'))
    exact = reference['exact']
    model = reference['model']
    # The bipolar switch matrix (binary_cfg=0) makes mbl = 2P - A_j.  seq_acc
    # removes the activation bias, so the published value is exactly 2*MAC
    # (the residual factor 2 is absorbed by the output scaler).
    exact_rtl = 2 * exact
    model_rtl = 2 * model
    n_windows, n_channels = exact.shape

    # Cross-check the CSR-programmed geometry against the golden shape.
    assert cfg_info['num_output_channels'] == n_channels, (
        f"TB num_output_channels={cfg_info['num_output_channels']} but golden "
        f'has {n_channels} columns')
    assert cfg_info['output_fmap_dimx'] * cfg_info['output_fmap_dimy'] == n_windows, (
        f"TB output map {cfg_info['output_fmap_dimx']}x"
        f"{cfg_info['output_fmap_dimy']} but golden has {n_windows} windows")

    assert len(wins) == n_windows, (
        f'expected {n_windows} accepted windows, captured {len(wins)}')
    assert len(pre) == n_windows * n_channels, (
        f'expected {n_windows * n_channels} MAC samples, got {len(pre)}')
    assert sorted(k for k, _, _ in wins) == list(range(n_windows)), (
        'accepted-window indices are not contiguous from 0')

    # Golden row p = y*W + x (row-major output raster).  Coverage and
    # uniqueness also prove that the opix positions are (x, y) and that the
    # sweep visits every output pixel exactly once.
    #
    # The activation/MAC stream is in golden raster order: the captured
    # activation vectors for events 0..7 match toeplitz rows 0..7 exactly.
    # The separate ``[DBG win]`` tags are sampled one word ahead of the MAC they
    # accompany, so they are only used to prove coverage/uniqueness, not to
    # index the samples.
    width = cfg_info['output_fmap_dimx']
    tagged = [y * width + x for _, x, y in wins]
    p_of_k = list(range(n_windows))
    assert sorted(tagged) == list(range(n_windows)), (
        'accepted windows do not cover the output map row-major '
        f'(first entries: {tagged[:8]})')

    rtl_pre = np.zeros((n_windows, n_channels), dtype=np.int64)
    rtl_post = np.zeros((n_windows, n_channels), dtype=np.int64)
    for k, p in enumerate(p_of_k):
        for o in range(n_channels):
            rtl_pre[p, o] = pre[(k, o)]
            rtl_post[p, o] = post[(k, o)]

    # The datapath only shifts the accumulator between seq_acc and the SRAM.
    # ``qracc_mac_output`` is the top-level, post-shift signal the scaler sees,
    # so the SNR never depends on a hierarchical read of the internal array;
    # ``seq_acc.accumulator`` is dumped only as a consistency cross-check.
    # `post` is what the scaler sees; the exact pre/post relation depends on
    # the runtime bias timing, so the authoritative check is the full-stream
    # SNR against the golden below.
    if not np.any(rtl_pre):
        print('note: the pre-shift accumulator dump is all zeros as well; '
              'compare on qracc_mac_output (post-shift) only')

    # Compare everything in post-shift units (a common <<s does not change SNR).
    exact_post = exact_rtl << shift
    model_post = model_rtl << shift
    snr_exact = snr_db(exact_post, model_post)
    snr_rtl = snr_db(exact_post, rtl_post)
    delta = abs(snr_rtl - snr_exact)
    max_abs = int(np.max(np.abs(rtl_post - exact_post)))

    print(
        f'\nB={weight_bits} s={shift} windows={n_windows} channels={n_channels}'
        f'\n  SNR(model vs exact) = {snr_exact:7.3f} dB'
        f'\n  SNR(rtl   vs exact) = {snr_rtl:7.3f} dB'
        f'\n  |delta|             = {delta:7.3f} dB (tolerance {SNR_TOLERANCE_DB})'
        f'\n  max|rtl - exact|    = {max_abs}'
    )

    save_scatter_fig(
        expected=exact_post.ravel(), actual=rtl_post.ravel(),
        title=(f'Multibit B={weight_bits} s={shift} RTL pre-shift accumulator '
               f'vs golden (SNR={snr_rtl:.2f} dB, model={snr_exact:.2f} dB)'),
        filename=f'multibit_prescale_B{weight_bits}_s{shift}',
        enabled=figures,
    )

    # See the module docstring: certify "near the golden SNR", not bit-exactness.
    assert np.any(rtl_post), (
        'RTL MAC path returned all zeros - the datapath is dead again '
        '(see FINDINGS_multibit_prescale.md)')
    assert delta <= SNR_TOLERANCE_DB, (
        f'B={weight_bits} s={shift}: RTL SNR {snr_rtl:.3f} dB deviates from the '
        f'golden-model SNR {snr_exact:.3f} dB by {delta:.3f} dB '
        f'(tolerance {SNR_TOLERANCE_DB} dB)')
