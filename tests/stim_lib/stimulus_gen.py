import numpy as np 
import os
import hwacctools.quantization.quant as quant
import hwacctools.comp_graph.compute as compute

def _hex_but_no_0x(x):
    return hex(x)[2:]

hex_but_no_0x = np.vectorize(_hex_but_no_0x)

def generate_top_inputs(
    savepath,
    stride,
    ifmap_shape,
    ifmap_bits,
    kernel_shape,
    kernel_bits,
    core_shape,
    seed = 0
):

    import torch # only import here so we don't affect the other tests
    import torch.nn.functional as F

    torch.manual_seed(seed)
    np.random.seed(seed)

    # Padding = 1 by default

    # Create a random image of integers
    t_ifmap = torch.randint(0, 2**(ifmap_bits), ifmap_shape, dtype=torch.int32)

    # Random kernel
    t_kern = torch.randint(0, 2**(kernel_bits), kernel_shape, dtype=torch.int32)

    # Convolve and add bias
    t_res = F.conv2d(t_ifmap, t_kern, padding=1, stride=stride).numpy()

    # Flatten the kernel
    t_matrix = t_kern.permute(0,2,3,1).numpy()
    t_matrix = t_matrix.reshape(t_kern.shape[0],-1).T

    # Flatten the image
    t_toeplitz = compute.toeplitzize_input(
        in_tensor=t_ifmap.squeeze(0).numpy(), 
        ksize=kernel_shape[-1], 
        strides=stride,
        channel_minor=True
    )

    a = t_toeplitz @ t_matrix
    output_shape = (
        ifmap_shape[0],
        kernel_shape[0],
        ifmap_shape[2]//stride, 
        ifmap_shape[3]//stride
    )
    out = a.T.reshape(*output_shape).astype(int)

    assert ( out == t_res ).all()

    # For now, extend the matrix into numRows and numCols to imitate a "mapped matrix"
    weight_array = np.zeros(core_shape, dtype=int)
    weight_array[:t_matrix.shape[0], :t_matrix.shape[1]] = t_matrix
    write_array = quant.array_bin_to_int(weight_array)

    # Software padding and channel minor
    ifmap_channel_minor = F.pad(t_ifmap, (1,1,1,1), mode='constant', value=0) # F.pad is weird asf
    ifmap_channel_minor = ifmap_channel_minor.permute(0,2,3,1) # N C H W -> N H W C
    ifmap_channel_minor = ifmap_channel_minor.numpy()

    # Press activations into 32b words of 4 elements each
    ifmap_channel_packed_ints = [int(i,base=16) for i in quant.as_packed_hex(ifmap_channel_minor)]
    ifmap_channel_packed_ints = np.array(ifmap_channel_packed_ints)

    # Generate scaler data and shifts
    # 0.06 heuristically gained for final values that are appreciable
    scale = np.random.rand(core_shape[1])*0.06 
    m0, shift = quant.vconvert_scale_to_shift_and_m0(scale, precision=16)
    int_scale = quant.vconvert_to_fixed_point_int(m0,16)
    scaler_data = int_scale * (2**4) + (-shift) # Pack into a single word
    # scaler_data = (int(int_scale) * (2**4)) + (-int(shift))
    # scaler_data = np.repeat(scaler_word, core_shape[1])

    res_dict = {
        'result': t_res,
        'toeplitz': t_toeplitz,
        'ifmap': ifmap_channel_packed_ints,
        'ifmap_ints': ifmap_channel_minor,
        'small_matrix': t_matrix,
        'matrix': write_array,
        'weights_np': weight_array, 
        'flat_output': out,
        'scaler_data': scaler_data
    }
    
    if savepath is not None:
        for key, value in res_dict.items():
            if value.dtype in ['int32','float64']:
                np.savetxt(f'{savepath}/{key}.txt', value.flatten(), fmt='%d')
            else:
                np.savetxt(f'{savepath}/{key}.txt', value.flatten(), fmt='%s')
            np.savetxt(f'{savepath}/{key}_shape.txt', value.shape, fmt='%d')

    return res_dict


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