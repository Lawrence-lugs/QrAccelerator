"""Compiler-only tests for internal channel Concat views.

These do not run RTL.  They lock down the compiler plan, the CSR fields, and
the command-stream choices that the eventual RTL implementation must honour.
"""
import numpy as np
import onnx
import pytest

from qracc_marp.compile.compile import (
    ACTMEM_BYTES,
    QrAccNodeCode,
    _build_internal_concat_views,
    _build_region_plan,
    bundle_config_into_write,
    traverse_and_compile_nx_graph,
)
from qracc_marp.constants import CSR_BASE_ADDR_HEX, CSR_REG_OUTPUT_VIEW
from qracc_marp.mapping import core
from qracc_marp.onnx_tools import onnx_utils

MODEL_PATH = 'onnx_models/mbv2_cifar10_int8.onnx'
CONCAT_OUT = 'split_4_concat_out'


def _mapping():
    nx = onnx.load(MODEL_PATH)
    return nx, core.NxModelMapping(
        nx, imc_core_size=(256, 256), dwc_core_size=32)


def _concat_node(nx):
    return next(n for n in nx.graph.node if n.op_type == 'Concat')


def test_mbv2_concat_plan_is_internal():
    nx, mapping = _mapping()
    views = _build_internal_concat_views(nx, mapping, 0, 13)
    v = views[CONCAT_OUT]
    assert v.supported, v.reason
    assert v.channels == (32, 32, 32)
    assert v.offsets == (0, 32, 64)
    assert v.total_channels == 96
    assert v.height == 16 and v.width == 16
    assert v.parent_bytes == 96 * 16 * 16
    assert v.output_bytes == 24 * 16 * 16
    assert v.live_bytes == v.parent_bytes + 96 * 16 * 16 + v.output_bytes
    assert v.live_bytes <= ACTMEM_BYTES


def test_concat_plan_capacity_fallback():
    nx, mapping = _mapping()
    views = _build_internal_concat_views(nx, mapping, 0, 13, capacity=1024)
    v = views[CONCAT_OUT]
    assert not v.supported
    assert 'exceeds' in v.reason


def test_concat_plan_non_channel_axis_fallback():
    nx, mapping = _mapping()
    concat = _concat_node(nx)
    for attr in concat.attribute:
        if attr.name == 'axis':
            attr.i = 3
    views = _build_internal_concat_views(nx, mapping, 0, 13)
    v = views[CONCAT_OUT]
    assert not v.supported
    assert 'axis' in v.reason


def test_split_configs_use_one_concat_group(monkeypatch):
    nx, mapping = _mapping()
    split = mapping.mapped_nodes[4]
    monkeypatch.setattr(
        QrAccNodeCode, '_generate_reference_output',
        lambda self: (np.zeros((1, 32, 16, 16), dtype=np.uint8),))
    parent_out = np.zeros((1, 96, 16, 16), dtype=np.uint8)
    u = QrAccNodeCode(
        mapped_node=split, mapped_bin=None, ifmap=parent_out[:, :32],
        imc_core_size=(256, 256), ws_core_size=32,
        weight_bits=8, weight_signed=True, nx_model=None,
        ifmap_channel_stride=96, ifmap_channel_offset=0,
        ofmap_channel_stride=96, ofmap_channel_offset=32,
    )
    c = u.config()
    assert c['ofmap_channel_stride'] == 96
    assert c['ofmap_channel_offset'] == 32
    writes = bundle_config_into_write(c, CSR_BASE_ADDR_HEX)
    view = next(w for w in writes
                if w.startswith(f'LOAD {0x10 + CSR_REG_OUTPUT_VIEW:08x}'))
    word = int(view.split()[2], 16)
    assert word & 0xFFFF == 96
    assert word >> 16 == 32


def test_region_plan_mbv2_accounts_for_all_live_groups():
    nx, mapping = _mapping()
    views = _build_internal_concat_views(nx, mapping, 0, 13)
    plan = _build_region_plan(nx, mapping, views, 0, 13)
    assert plan.supported
    assert plan.peak_live_bytes >= 96 * 16 * 16 + 96 * 16 * 16
    assert plan.peak_live_bytes <= ACTMEM_BYTES
    assert len(plan.regions) == 1
    region = plan.regions[0]
    assert region.entries == ('input.1_quantized',)
    assert region.exits == (
        '/features/features.2/conv/conv.2/Conv_output_0_quantized',)
    assert any(v.role == 'concat_group' and v.channel_offset == 0
               and v.pixel_stride == 96 for v in region.views)
    assert any(v.role == 'slice' and v.channel_offset == 32
               for v in region.views)


def test_region_plan_splits_linear_over_budget():
    nx, mapping = _mapping()
    views = _build_internal_concat_views(nx, mapping, 0, 5)
    plan = _build_region_plan(nx, mapping, views, 0, 5, capacity=20000)
    assert len(plan.regions) > 1
    assert not plan.supported
    assert any(r.supported for r in plan.regions)


def test_region_split_keeps_concat_group_together():
    nx, mapping = _mapping()
    views = _build_internal_concat_views(nx, mapping, 0, 13)
    plan = _build_region_plan(nx, mapping, views, 0, 13, capacity=40000)
    group_nodes = {8, 9, 10, 12}
    containing = [r for r in plan.regions
                  if group_nodes.issubset(set(r.node_ids))]
    assert len(containing) == 1
    assert any(r.supported for r in plan.regions)
    assert not plan.supported


def test_region_plan_rejects_over_budget():
    nx, mapping = _mapping()
    views = _build_internal_concat_views(nx, mapping, 0, 13)
    plan = _build_region_plan(nx, mapping, views, 0, 13, capacity=1024)
    assert not plan.supported
    assert 'exceeds' in plan.regions[0].reason


def test_traverse_uses_internal_concat_and_suppresses_split_readout():
    nx, _ = _mapping()
    np.random.seed(0)
    d = {'input.1': np.random.rand(1, 3, 32, 32).astype(np.float32)}
    commands = traverse_and_compile_nx_graph(
        nx, d, until=13, weight_bits=8, real_activations=True)

    split_offsets = []
    for i, line in enumerate(commands):
        if line.startswith('LOAD 00000018'):
            word = int(line.split()[2], 16)
            stride = word & 0xFFFF
            off = word >> 16
            if stride == 96 and off in (0, 32, 64):
                split_offsets.append((stride, off))

    assert (96, 0) in split_offsets
    assert (96, 32) in split_offsets
    assert (96, 64) in split_offsets

    # The projection must consume the group from ACTMEM, not a fresh external
    # ifmap, and the intermediate splits must not be externally read out.
    project_lines = [s for s in commands
                     if 'conv.2/Conv_quant' in s and 'NODE' in s]
    assert any('will read ifmap' in s and 'ACTMEM' in s
               for s in project_lines)
    for i in range(3):
        assert not any(
            f'split_4_qconv_{i}' in s and 'write ofmap' in s
            for s in commands)
        assert not any(
            f'split_4_qconv_{i}' in s and 'read ifmap' in s
            and 'external memory' in s
            for s in commands)
