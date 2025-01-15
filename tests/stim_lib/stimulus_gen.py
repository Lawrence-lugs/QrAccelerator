import numpy as np 
import os
import hwacctools.quantization.quant as quant

def generate_qracc_inputs(
    wDimX = 8,
    wDimY = 128,
    xBatches = 50,
    xTrits = 4,
    outBits = 4,
    seed = 0,
    weight_mode = 'bipolar'
):
    'Generates integer weights and inputs, including clipped integer reference outputs.'

    np.random.seed(seed)
    wShape = (wDimX, wDimY)
    xShape = (xBatches, wDimY)

    if weight_mode=='binary':
        w = np.random.randint(0,2, wShape) # Binary Weights
        x = np.random.randint(-(2**(xTrits)), 2**(xTrits),xShape)
    elif weight_mode=='bipolar':
        w = np.random.randint(0,2, wShape)*2-1 # Bipolar Weights
        x = np.random.randint(-(2**(xTrits)), 2**(xTrits),xShape)
    else:
        raise ValueError('Invalid weight_mode')
    wx = w @ x.T

    wxBits = quant.get_array_bits(wx)
    wx_outBits = quant.saturating_clip(wx, inBits = wxBits, outBits = outBits)

    return w, x, wx_outBits