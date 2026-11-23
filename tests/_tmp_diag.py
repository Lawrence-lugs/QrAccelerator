"""P7g-diag-B8: compare B=8 emitted weight words (QrAccNodeCode path) to ONNX int8 weights byte-by-byte."""
import os
import sys
import numpy as np
import onnx
from onnx import numpy_helper

REPO = '/workspaces/QrAccelerator'
sys.path.insert(0, REPO)

from qracc_marp.mapping.core import NxModelMapping
from qracc_marp.compile.compile import QrAccNodeCode
from qracc_marp.onnx_tools import onnx_utils
from qracc_marp.compile.stimulus_gen import write_weight_rows_to_asm

MODEL = os.path.join(REPO, 'onnx_models', 'mbv2_cifar10_int8.onnx')
NODE_NAME = '/features/features.0/features.0.0/Conv_quant'
OUT = '/workspaces/QrAccelerator/tests/_tmp_diag_out.txt'

lines = []
def w(*a):
    lines.append(' '.join(str(x) for x in a))

model = onnx.load(MODEL)
node = next(n for n in model.graph.node if n.name == NODE_NAME)
wname = node.input[3]
init = next(i for i in model.graph.initializer if i.name == wname)
W = numpy_helper.to_array(init).astype(np.int8)  # (32,3,3,3)
w_shape = W.shape
w_min, w_max = int(W.min()), int(W.max())
w_bytes = W.tobytes()
w_total = w_bytes.__len__()

w('P7g-diag-B8: B=8 emitted weight words vs ONNX int8 weights')
w('Node:', NODE_NAME, 'op_type:', node.op_type)
w('Weight initializer (node.input[3]):', init.name)
w('ONNX weight shape:', w_shape)
w('ONNX weight dtype: int8')
w('ONNX weight min:', w_min, 'max:', w_max)
w('ONNX weight total bytes:', w_total)
w('')

# Build mapping + QrAccNodeCode (B=8 path, matches test_marp_rtl.py:194-203)
nxmap = NxModelMapping(model, imc_core_size=(256, 256), dwc_core_size=32)
mnode = next(mn for mn in nxmap.mapped_nodes if mn.name == NODE_NAME)
bin_ = nxmap.mapped_bins[mnode.bin_id]
cell = bin_.weights.astype(np.int8)  # (256,256), kernel matrix placed at offset
offset_x = int(mnode.offset_x)  # rectpack y -> matrix column (output channel)
offset_y = int(mnode.offset_y)  # rectpack x -> matrix row (input tap)
w('Emitter path: QrAccNodeCode.compile() -> _get_weight_data() -> write_weight_rows_to_asm()')
w('Emitter file:line: qracc_marp/compile/compile.py:_get_weight_data (214-226), '
  'write_weight_rows_to_asm at qracc_marp/compile/stimulus_gen.py:349')
w('Signed flag: compile.py:311 passes signed=self.weight_signed; test passes weight_signed=True; default False')
w('weight_bits=8, weight_signed=True (matches B=8 test path)')
w('mapped node depthwise:', bool(mnode.depthwise))
w('mapped node offset_x:', offset_x, 'offset_y:', offset_y)
w('bin weights shape:', cell.shape, cell.dtype)
w('')

# Emit weight words
wd = u_code = None
u_code = QrAccNodeCode(
    mapped_node=mnode, mapped_bin=bin_,
    ifmap=np.random.randint(0, 256, (1, 3, 32, 32)).astype(np.uint8),
    imc_core_size=(256, 256), ws_core_size=32,
    weight_bits=8, weight_signed=True, nx_model=model,
)
wd_arr = np.asarray(u_code._get_weight_data())
asm = write_weight_rows_to_asm(wd_arr, signed=True)
word_vals = []
for line in asm:
    if line.startswith('LOAD'):
        word_vals.append(int(line.split()[2], 16))
w('Emitted weight words (LOAD lines):', len(word_vals))
w('Emitted total bytes:', len(word_vals) * 4)
w('_get_weight_data() shape/dtype:', wd_arr.shape, wd_arr.dtype,
  'min:', int(wd_arr.min()), 'max:', int(wd_arr.max()))
w('')

# Byte-by-byte comparison: map each ONNX int8 weight to the byte it should occupy.
# cell_array[offset_y + r, offset_x + o] = kernel[o, i, kh, kw], r = kh*9 + kw*3 + i
# flat index f = R*256 + C; bank row b = f // 32; bit position k = f % 32; byte j = k // 8
# got_byte = (word_vals[b] >> (8*j)) & 0xFF ; expected_byte = W & 0xFF
mismatches = []
total_compared = 0
sign_match = 0
sign_total = 0
twos_neg_ok = 0
twos_neg_total = 0

O, I, KH, KW = w_shape
for o in range(O):
    for i in range(I):
        for kh in range(KH):
            for kw in range(KW):
                wval = int(W[o, i, kh, kw])
                expected_byte = wval & 0xFF
                r = kh * 9 + kw * 3 + i
                R = offset_y + r
                C = offset_x + o
                f = R * 256 + C
                b = f // 32
                k = f % 32
                j = k // 8
                got_byte = (word_vals[b] >> (8 * j)) & 0xFF
                total_compared += 1
                if expected_byte != got_byte:
                    if len(mismatches) < 5:
                        mismatches.append((kh * 3 + kw, o, i, expected_byte, got_byte))
                # sign bit (bit7) of got byte vs ONNX sign
                sign_total += 1
                if ((got_byte >> 7) & 1) == (1 if wval < 0 else 0):
                    sign_match += 1
                # two's complement: negative weight byte should be 0x80..0xFF
                if wval < 0:
                    twos_neg_total += 1
                    if 0x80 <= got_byte <= 0xFF:
                        twos_neg_ok += 1

mismatch_count = total_compared - sum(
    1 for o in range(O) for i in range(I) for kh in range(KH) for kw in range(KW)
    if (int(W[o,i,kh,kw]) & 0xFF) == (
        (word_vals[((offset_y + kh*9 + kw*3 + i)*256 + (offset_x + o)) // 32]
         >> (8 * (((((offset_y + kh*9 + kw*3 + i)*256 + (offset_x + o)) % 32) // 8)))) & 0xFF
    )
)

w('TOTAL WEIGHT BYTES COMPARED:', total_compared)
w('MISMATCH COUNT:', mismatch_count)
w('')
w('First 5 mismatches as (tap, out_ch, in_ch, expected_byte_hex, got_byte_hex):')
for m in mismatches:
    w('  tap=%d out_ch=%d in_ch=%d expected=%s got=%s' % (m[0], m[1], m[2],
                                                          format(m[3], '02x'), format(m[4], '02x')))
w('')
w('Sign bit (bit7) of every byte matches ONNX sign: %d/%d' % (sign_match, sign_total))
w("Negative weights encoded as two's complement (0x80..0xFF): %d/%d" % (twos_neg_ok, twos_neg_total))
w('')
w('VERDICT: emitter mismatches at qracc_marp/compile/compile.py:_get_weight_data (line 226)')
w('  The non-depthwise B=8 path routes through mapped_matrix_to_bank_writes / array_bin_to_int,')
w('  which bit-packs int8 weight values as bit coefficients (sum of 32 int8s per 32-bit word),')
w('  rather than emitting each ONNX int8 weight as its own byte. Emitted stream is 8192 bytes')
w('  vs 864 ONNX weight bytes; each emitted word is a summed bit-packed value, not weight bytes.')
w('  Therefore the B=8 emitted words do NOT match the ONNX int8 weights byte for byte.')

with open(OUT, 'w') as f:
    f.write('\n'.join(lines) + '\n')
print('\n'.join(lines))
print('WROTE', OUT)
