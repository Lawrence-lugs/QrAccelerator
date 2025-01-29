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
    col_symmetric = False,
    rangeBits = None,
    x_repeat = False,
    clip_output = True
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

    if x_repeat:
        x = np.random.randint(-(2**(xTrits)-1), 2**(xTrits),wDimY)
        x = x.repeat(xBatches).reshape(wDimY, xBatches).T
    else:
        x = np.random.randint(-(2**(xTrits)-1), 2**(xTrits),xShape)
    wx = w @ x.T

    # Get_array_bits is incorrect. The real bit count depends on the range of the input data
    # wxBits = quant.get_array_bits(wx)

    if rangeBits is None:
        wxBits = np.log2(wDimY) + 1 # +1 because of bipolar rep (-128,128) vs (0,128)
    else:
        wxBits = rangeBits

    if clip_output:
        wx_outBits = quant.saturating_clip(wx, inBits = wxBits, outBits = outBits)
    else:
        wx_outBits = wx
    return w, x, wx_outBits.T