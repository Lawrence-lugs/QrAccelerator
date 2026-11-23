"""S3: Verify real depthwise words against ONNX weights.

For tap t in 0..8 and channel c in 0..31:
  word index = t*8 + c//4, byte = c%4
  byte must equal int8 W[c, 0, t//3, t%3] (two's complement as uint8).
Reports mismatch count and first mismatch.
"""
import sys
import numpy as np
import onnx
from onnx import numpy_helper

sys.path.insert(0, '/workspaces/QrAccelerator')

MODEL = '/workspaces/QrAccelerator/onnx_models/mbv2_cifar10_int8_binary.onnx'
WORDS = '/workspaces/QrAccelerator/tests/_tmp_dw/p10_dw_words_real.txt'

model = onnx.load(MODEL)
init = {i.name: numpy_helper.to_array(i) for i in model.graph.initializer}

# depthwise weight (32,1,3,3) int8
W = None
for i in model.graph.initializer:
    if list(i.dims) == [32, 1, 3, 3]:
        W = numpy_helper.to_array(i).astype(np.int8)
        wname = i.name
        break
assert W is not None, 'no (32,1,3,3) initializer'
print('W:', wname, W.shape, W.dtype)

# sanity: print channel values for tap (0,0)
print('W[:,0,0,0] all 32 channels:', W[:, 0, 0, 0])

words = np.array([int(l.strip(), 16) for l in open(WORDS) if l.strip()], dtype=np.uint32)
print('word count:', len(words))

mismatches = 0
first = None
for t in range(9):
    kh, kw = t // 3, t % 3
    for c in range(32):
        word_idx = t * 8 + (c // 4)
        byte_idx = c % 4
        got = int((int(words[word_idx]) >> (byte_idx * 8)) & 0xFF)
        want = int(W[c, 0, kh, kw]) & 0xFF  # two's complement as uint8
        if got != want:
            mismatches += 1
            if first is None:
                first = (t, c, word_idx, byte_idx, got, want,
                         int(W[c, 0, kh, kw]))

print('mismatch count:', mismatches)
if first is not None:
    t, c, wi, bi, got, want, wval = first
    print('first mismatch: tap=%d ch=%d word_idx=%d byte=%d got=0x%02x want=0x%02x (W=%d)'
          % (t, c, wi, bi, got, want, wval))

# also report how many words have bytes1-3 == 00 (for comparison with p9)
b13_zero = 0
all4_nz = 0
for w in words:
    b = [(int(w) >> s) & 0xFF for s in (24, 16, 8, 0)]
    if b[1] == 0 and b[2] == 0 and b[3] == 0:
        b13_zero += 1
    if all(x != 0 for x in b):
        all4_nz += 1
print('words bytes1-3==00:', b13_zero, 'of', len(words))
print('words all 4 bytes nonzero:', all4_nz)
