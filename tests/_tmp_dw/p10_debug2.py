"""Confirm import source and test the packing expression in isolation."""
import sys
import numpy as np

sys.path.insert(0, '/workspaces/QrAccelerator')
from qracc_marp.compile import stimulus_gen as sg
print('module file:', sg.__file__)
print('kernel_to_writes file:', sg.kernel_to_writes.__code__.co_filename)

kf = np.array([[15, 231, 5, 2]], dtype=np.uint8)
v = (kf[0,3] & 0xFF) << 24 | (kf[0,2] & 0xFF) << 16 | (kf[0,1] & 0xFF) << 8 | (kf[0,0] & 0xFF)
print('isolated expr: 0x%08x' % int(v))

# Now call the real function on a tiny array
ph = np.array([[[[15, -25, 5, 2]]]], dtype=np.int8)  # (1,1,1,4)
w = sg.kernel_to_writes(ph, channels=4, hexes=False)
print('tiny word[0] = 0x%08x (expect 0x0205e70f)' % int(w[0]))
