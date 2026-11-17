import copy
import os
import sys

import numpy as np
import onnx
import onnxruntime as ort
from onnx import helper

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from qracc_marp.quantization.quant import quantize_int8_to_bits

from .conftest import _normalize_cifar

MODEL_PATH = os.path.join(REPO_ROOT, 'onnx_models', 'mbv2_cifar10_int8.onnx')
IMAGE_PATH = os.path.join(REPO_ROOT, 'onnx_models', 'cifar10_test_bird4.jpg')
NODE_NAME = '/features/features.0/features.0.0/Conv_quant'
REF_DIR = r'C:\Users\lafqu\AppData\Local\Temp\opencode\multibit_ref'


def _find_node(model, node_name):
    for n in model.graph.node:
        if n.name == node_name:
            return n
    raise AssertionError(f'node {node_name!r} not found in model')


def _weight_initializer(model, node_name):
    node = _find_node(model, node_name)
    assert node.op_type == 'QLinearConv', f'node {node_name} is {node.op_type}, expected QLinearConv'
    wname = node.input[3]
    for init in model.graph.initializer:
        if init.name == wname:
            return node, init
    raise AssertionError(f'weight initializer {wname!r} not found')


def _output_info(model, node_name):
    node = _find_node(model, node_name)
    out_name = node.output[0]
    for v in model.graph.value_info:
        if v.name == out_name:
            return v
    inf = onnx.shape_inference.infer_shapes(model)
    for v in inf.graph.value_info:
        if v.name == out_name:
            return v
    return None


def _shape_of(vi):
    if vi is None:
        return None
    dims = []
    for d in vi.type.tensor_type.shape.dim:
        if d.HasField('dim_value'):
            dims.append(d.dim_value)
        else:
            return None
    return dims or None


def _run_with_output(model, node_name, input_name, input_data):
    model = copy.deepcopy(model)
    node = _find_node(model, node_name)
    out_name = node.output[0]
    vi = _output_info(model, node_name)
    elem_type = vi.type.tensor_type.elem_type if vi is not None else onnx.TensorProto.INT8
    shape = _shape_of(vi)
    out_info = helper.make_tensor_value_info(out_name, elem_type, shape)
    model.graph.output.append(out_info)
    sess = ort.InferenceSession(model.SerializeToString(), providers=['CPUExecutionProvider'])
    return sess.run([out_name], {input_name: input_data})[0]


def same_b_reference(model_path, node_name, B):
    """ORt reference for conv node with weights reduced to B bits and re-scaled to int8."""
    model = onnx.load(model_path)
    node, init = _weight_initializer(model, node_name)
    w = onnx.numpy_helper.to_array(init)
    q = quantize_int8_to_bits(w, B, signed=True)
    w_eff = np.clip(q * (2 ** (8 - B)), -128, 127).astype(np.int8)
    new_init = onnx.numpy_helper.from_array(w_eff, name=init.name)
    for idx, old in enumerate(model.graph.initializer):
        if old.name == init.name:
            model.graph.initializer[idx].CopyFrom(new_init)
            break
    input_name = model.graph.input[0].name
    input_data = _normalize_cifar(IMAGE_PATH)
    return _run_with_output(model, node_name, input_name, input_data)


def test_b8_matches_int8():
    model = onnx.load(MODEL_PATH)
    input_name = model.graph.input[0].name
    input_data = _normalize_cifar(IMAGE_PATH)
    ref = same_b_reference(MODEL_PATH, NODE_NAME, 8)
    plain = _run_with_output(model, NODE_NAME, input_name, input_data)
    assert np.array_equal(ref, plain)


def test_b2_b4_differ():
    out8 = same_b_reference(MODEL_PATH, NODE_NAME, 8)
    for B in (2, 4):
        out = same_b_reference(MODEL_PATH, NODE_NAME, B)
        assert np.all(np.isfinite(out)), f'B={B} output not finite'
        assert not np.array_equal(out, out8), f'B={B} output equals B=8 output'


def test_saves_refs():
    os.makedirs(REF_DIR, exist_ok=True)
    safe = NODE_NAME.lstrip('/').replace('/', '_')
    for B in (2, 4, 8):
        out = same_b_reference(MODEL_PATH, NODE_NAME, B)
        path = os.path.join(REF_DIR, f'{safe}_B{B}.npy')
        np.save(path, out)
        assert os.path.exists(path)
