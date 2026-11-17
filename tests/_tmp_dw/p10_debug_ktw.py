"""Debug kernel_to_writes internals for the depthwise case."""
import sys
import numpy as np
import onnx
from onnx import numpy_helper

sys.path.insert(0, '/workspaces/QrAccelerator')
from qracc_marp.compile.stimulus_gen import kernel_to_writes

MODEL = '/workspaces/QrAccelerator/onnx_models/mbv2_cifar10_int8_binary.onnx'
model = onnx.load(MODEL)
init = {i.name: numpy_helper.to_array(i) for i in model.graph.initializer}
W = None
for i in model.graph.initializer:
    if list(i.dims) == [32, 1, 3, 3]:
        W = numpy_helper.to_array(i).astype(np.int8)
        break
ph = W.transpose(1, 2, 3, 0)  # (1,3,3,32)
print('ph shape', ph.shape, 'dtype', ph.dtype)
print('ph[0,0,0,:] =', ph[0, 0, 0, :])  # W[:,0,0,0]

# Replicate kernel_to_writes steps manually
channels = 32
kernel_flat = ph.reshape(-1, channels)
print('kernel_flat shape', kernel_flat.shape, 'dtype', kernel_flat.dtype)
print('kernel_flat[0,:8] =', kernel_flat[0, :8])
kernel_flat2 = kernel_flat.reshape(-1, 4).astype(np.uint8)
print('kernel_flat2 shape', kernel_flat2.shape)
print('kernel_flat2[0] =', kernel_flat2[0])  # expect [15, 0xe7, 5, 2]

words = kernel_to_writes(ph, channels=32, hexes=False)
words = np.asarray(words, dtype=np.uint32)
print('word[0] = 0x%08x' % int(words[0]))
print('word[0] bytes (b3,b2,b1,b0) =', [(int(words[0]) >> s) & 0xFF for s in (24, 16, 8, 0)])
