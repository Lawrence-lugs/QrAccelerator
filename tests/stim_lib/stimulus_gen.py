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
    weight_mode = 'bipolar',
    col_symmetric = False
):
    '''
    Generates integer weights and inputs, including clipped integer reference outputs.
    Parameters:
    wDimX : int -- Number of columns
    wDimY : int -- Number of rows
    xBatches : int -- Number of batches
    xTrits : int -- Number of trits for input data
    outBits : int -- Number of bits for output data
    seed : int -- Random seed
    weight_mode : str -- 'binary' or 'bipolar'
    col_symmetric : bool -- If True, all columns will have the same output value
    '''
    np.random.seed(seed)
    wShape = (wDimX, wDimY)
    xShape = (xBatches, wDimY)

    if col_symmetric:
        # In this mode, every column will have the same output value
        print('[STIM_GEN] Generating symmetric columns')
        if weight_mode=='binary':
            w = np.random.randint(0,2, wDimY)
            w = w.repeat(wDimX).reshape(wDimY, wDimX).T
        elif weight_mode=='bipolar':
            w = np.random.randint(0,2, wShape)*2-1
            w = w.repeat(wDimX).reshape(wDimY, wDimX).T
        else:
            raise ValueError('Invalid weight_mode')
    else:
        print('[STIM_GEN] Generating random weights')
        if weight_mode=='binary':
            w = np.random.randint(0,2, wShape) # Binary Weights
        elif weight_mode=='bipolar':
            w = np.random.randint(0,2, wShape)*2-1 # Bipolar Weights
        else:
            raise ValueError('Invalid weight_mode')

    x = np.random.randint(-(2**(xTrits)-1), 2**(xTrits),xShape)
    wx = w @ x.T

    wxBits = quant.get_array_bits(wx)
    wx_outBits = quant.saturating_clip(wx, inBits = wxBits, outBits = outBits)

    return w, x, wx_outBits.T