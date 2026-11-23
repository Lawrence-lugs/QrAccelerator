"""Dump REAL depthwise weight words for MARP node mnode1 (ONNX node2, group=32, 3x3).

Loads onnx_models/mbv2_cifar10_int8_binary.onnx, finds the depthwise conv node
named node2, extracts its int8 weight W (32,1,3,3), builds
physical_kernel_hwc = W.transpose(1,2,3,0) (1,3,3,32) and calls
qracc_marp.compile.stimulus_gen.kernel_to_writes(..., channels=32, hexes=False).
Saves one hex uint32 word per line. Expected 72 words.
"""
import sys
import os

import numpy as np
import onnx
from onnx import numpy_helper

sys.path.insert(0, '/workspaces/QrAccelerator')
from qracc_marp.compile.stimulus_gen import kernel_to_writes

MODEL = '/workspaces/QrAccelerator/onnx_models/mbv2_cifar10_int8_binary.onnx'
OUT = '/workspaces/QrAccelerator/tests/_tmp_dw/p10_dw_words_real.txt'

model = onnx.load(MODEL)
graph = model.graph

print('=== Nodes in graph ===')
for node in graph.node:
    print(' ', node.name, node.op_type)

# Find depthwise conv node (group=32, 3x3). In this exported MBV2 the convs are
# QLinearConv; the weight is input[3]. There is no node literally named "node2";
# the MARP mnode1 depthwise node corresponds to the QLinearConv whose weight has
# shape (32,1,3,3) and group==32.
init = {i.name: numpy_helper.to_array(i) for i in graph.initializer}

target = None
w_name = None
for node in graph.node:
    if node.op_type != 'QLinearConv':
        continue
    # QLinearConv: X, X_scale, X_zero_point, W, W_scale, W_zero_point, ...
    cand_w = node.input[3] if len(node.input) > 3 else None
    if cand_w is None or cand_w not in init:
        continue
    cand = init[cand_w]
    if list(cand.shape) != [32, 1, 3, 3]:
        continue
    group = 1
    for attr in node.attribute:
        if attr.name == 'group':
            group = attr.i
    if group == 32:
        target = node
        w_name = cand_w
        break

assert target is not None, 'depthwise QLinearConv (group=32, weight (32,1,3,3)) not found'
print('Found node:', target.name, target.op_type, 'group=32')
print('W name:', w_name, 'shape:', init[w_name].shape, 'dtype:', init[w_name].dtype)
W = init[w_name].astype(np.int8)
assert W.shape == (32, 1, 3, 3), W.shape

physical_kernel_hwc = W.transpose(1, 2, 3, 0)  # (1,3,3,32) KHWC
print('physical_kernel_hwc shape:', physical_kernel_hwc.shape)

words = kernel_to_writes(physical_kernel_hwc, channels=32, hexes=False)
words = np.asarray(words, dtype=np.uint32)
print('word count:', len(words))

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, 'w') as f:
    for w in words:
        f.write(f'{int(w) & 0xFFFFFFFF:08x}\n')
print('saved to', OUT)

# Quick diagnostics
n_all_nonzero = int(np.sum(np.all(((words >> np.array([24, 16, 8, 0], dtype=np.uint32)) & 0xFF) != 0, axis=1)))
n_bytes13_zero = int(np.sum((((words >> 8) & 0xFFFF) == 0)))
print('words with all 4 bytes nonzero:', n_all_nonzero)
print('words with bytes 1-3 == 00:', n_bytes13_zero)
