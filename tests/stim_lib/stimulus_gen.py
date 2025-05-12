import numpy as np 
import os
import hwacctools.quantization.quant as quant
from hwacctools.comp_graph import compute, cgraph, cnodes
from hwacctools import onnx_utils
import onnx
import torch.nn.functional as F
import torch 

def _hex_but_no_0x(x):
    return hex(x)[2:]

hex_but_no_0x = np.vectorize(_hex_but_no_0x)

def generate_random_torch_conv(
    ifmap_shape,
    ifmap_bits,
    kernel_shape,
    kernel_bits,
    stride,
    seed = 0
):
    
    t_ifmap = torch.randint(0, 2**(ifmap_bits), ifmap_shape, dtype=torch.int32)
    t_kern = torch.randint(0, 2**(kernel_bits), kernel_shape, dtype=torch.int32)
    t_res = F.conv2d(t_ifmap, t_kern, padding=1, stride=stride).numpy()

    t_matrix = t_kern.permute(0,2,3,1).numpy()
    t_matrix = t_matrix.reshape(t_kern.shape[0],-1).T

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

    return t_res, t_matrix, t_ifmap, t_toeplitz, out

def generate_tensor(shape, mode = 'random',seed = 0):
    if mode == 'random':
        np.random.seed(seed)
        return np.random.rand(*shape)
    elif mode == 'linspace':
        return np.linspace(0, 1, num = np.prod(shape)).reshape(shape)


def sample_onnx_qlinearconv(
    ifmap_shape,
    ifmap_bits,
    kernel_shape,
    kernel_bits,
    kernel_dtype,
    pads,
    stride,
    weight_density = 0.5,
    seed = 0,
    acts_mode = 'random',
    weight_mode = 'random'
):
    
    '''
    Generates a sample QLinearConv

    supports precisions < 8

    only uint8 ifmap

    acts_mode can be 'counting' or 'random'
    '''

    np.random.seed(seed)

    if acts_mode not in ['counting','random']:
        raise ValueError(f"acts_mode must be 'counting' or 'random', got {acts_mode}")

    qa_proto = quant.QuantizedTensor(shape = ifmap_shape, precision = ifmap_bits, mode='3sigma')
    if acts_mode == 'counting':
        ifmap_size = np.prod(ifmap_shape)
        a_qvals = np.arange(0,ifmap_size, dtype=np.uint8) % 100
        a_qvals = a_qvals.reshape(ifmap_shape)
        qa = quant.QuantizedTensor(quantized_values = a_qvals, scale = qa_proto.scale, zero_point=0) 
    if acts_mode == 'random':
        qa = qa_proto   

    # 1-bit qb scales and zero point heuristically guessed from
    # a standard normal distribution 
    if kernel_bits == 1:
        # b = np.random.randint(0,2, kernel_shape)
        if weight_mode == 'random':
            dist = np.random.rand(*kernel_shape)
            b = (dist < weight_density).astype(int)
        elif weight_mode == 'spatial':
            b = np.zeros(kernel_shape)
            for k in range(kernel_shape[0]):
                # b[k][0][2][2] = 1
                b[k][0][k % 3][k % 3] = 1
        qb = quant.QuantizedTensor(quantized_values = b, scale = 0.1, zero_point=0)
    else:
        qb = quant.QuantizedTensor(shape = kernel_shape, precision = kernel_bits, mode='3sigma')

    ofmap_shape = (
        ifmap_shape[0],
        kernel_shape[0],
        (ifmap_shape[2] - kernel_shape[2] + 2 * pads[0]) // stride + 1,
        (ifmap_shape[3] - kernel_shape[3] + 2 * pads[2]) // stride + 1
    )

    # infer doesn't actually need this
    sample_outs = quant.QuantizedTensor(shape = ofmap_shape, precision = 8, mode='3sigma')

    qa.quantized_values = qa.quantized_values.astype(np.uint8)
    qb.quantized_values = qb.quantized_values.astype(kernel_dtype)
    sample_outs.quantized_values = sample_outs.quantized_values.astype(np.uint8)

    node = onnx.helper.make_node(
        "QLinearConv",
        inputs=[
            "x",
            "x_scale",
            "x_zero_point",
            "w",
            "w_scale",
            "w_zero_point",
            "y_scale",
            "y_zero_point",
        ],
        outputs=["y"],
        pads = pads,
        strides = (stride, stride),
    )

    scale_x = np.array(qa.scale, dtype=np.float32)
    zp_x = np.array(qa.zero_point, dtype=np.uint8)
    scale_w = np.array(qb.scale, dtype=np.float32)
    zp_w = np.array(qb.zero_point, dtype=kernel_dtype)
    scale_y = np.array(sample_outs.scale, dtype=np.float32)
    zp_y = np.array(sample_outs.zero_point, dtype=np.uint8)

    node_initializers = [
        qa.quantized_values,
        scale_x,
        zp_x,
        qb.quantized_values,
        scale_w,
        zp_w,
        scale_y,
        zp_y,
    ]

    outs = onnx_utils.infer_node_output(
        node,
        inputs=node_initializers,
        outputs=[sample_outs.quantized_values],
        name="test_qlinearconv",
    )

    wadds = zp_x * qb.quantized_values.sum(axis=(1,2,3))

    cnode_params = {
        'scale_x' : scale_x,
        'zp_x' : zp_x,
        'scale_w' : np.repeat(scale_w, kernel_shape[0]),
        'zp_w' : zp_w,
        'scale_y' : scale_y,
        'zp_y' : zp_y,
        'kernel' : qb.quantized_values,
        'biases' : np.zeros((kernel_shape[0],), dtype=np.int32),
        'strides' : stride,
        'group' : 1
    }
    
    cnode = cnodes.from_QLinearConv(None, node, channel_minor=True, qparams = cnode_params)

    # Parse required offsets
    scaler_params = {
        'scale' : scale_x * scale_w / scale_y,
        'ifmap_zp_offset' : zp_x * qb.quantized_values.sum(axis=(1,2,3)),
        'output_zp' : zp_y,
        'nx_node' : node,
        'gph_node' : cnode,
        'cnode_params' : cnode_params,
        'zp_x' : zp_x,
    }

    # Return expected tensor values
    t_kern = qb.quantized_values
    t_ifmap = qa.quantized_values
    t_matrix = t_kern.transpose(0,2,3,1)
    t_matrix = t_matrix.reshape(t_kern.shape[0],-1).T
    t_toeplitz = compute.toeplitzize_input(
        in_tensor=t_ifmap.squeeze(axis=0), 
        ksize=kernel_shape[-1], 
        strides=stride,
        channel_minor=True,
        zero_point=zp_x
    )
    t_res = outs[0].transpose(0,2,3,1)

    return t_res, t_matrix, t_ifmap, t_toeplitz, scaler_params

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

    torch.manual_seed(seed)
    np.random.seed(seed)
    
    print("[STIM_GEN] Generating Sample QLinearConv")
    print(f"t_res, t_matrix, t_ifmap, t_toeplitz = sample_onnx_qlinearconv(ifmap_shape={ifmap_shape},ifmap_bits={ifmap_bits},kernel_shape={kernel_shape},kernel_bits={kernel_bits},kernel_dtype = np.int8,pads = (1,1,1,1),stride = {stride},seed = {seed}),weight_density=0.05,acts_mode='counting'")

    t_res, t_matrix, t_ifmap, t_toeplitz, scaler_params = sample_onnx_qlinearconv(
        ifmap_shape=ifmap_shape,
        ifmap_bits=ifmap_bits,
        kernel_shape=kernel_shape,
        kernel_bits=kernel_bits,
        kernel_dtype = np.int8,
        pads = (1,1,1,1),
        stride = stride,
        seed = seed,
        # weight_density=0.05,
        # acts_mode='counting',
        # weight_mode='spatial'
    )
    out = t_res

    # For now, extend the matrix into numRows and numCols to imitate a "mapped matrix"
    weight_array = np.zeros(core_shape, dtype=int)
    # t_matrix = t_matrix[:,::-1] # Reverse the matrix to match hardware [31:0]
    weight_array[:t_matrix.shape[0], :t_matrix.shape[1]] = t_matrix
    weight_array_banked = weight_array.reshape(-1, 32)
    write_array = quant.array_bin_to_int(weight_array_banked)

    # Software padding and channel minor
    t_ifmap = torch.from_numpy(t_ifmap)
    zp_x = float(scaler_params['zp_x'])
    ifmap_channel_minor = F.pad(t_ifmap, (1,1,1,1), mode='constant', value=zp_x) # F.pad is weird asf
    ifmap_channel_minor = ifmap_channel_minor.permute(0,2,3,1) # N C H W -> N H W C
    ifmap_channel_minor = ifmap_channel_minor.numpy()

    # Press activations into 32b words of 4 elements each
    ifmap_channel_packed_ints = [int(i,base=16) for i in quant.as_packed_hex(ifmap_channel_minor)]
    ifmap_channel_packed_ints = np.array(ifmap_channel_packed_ints)

    # Generate scaler data and shifts
    scale = scaler_params['scale']

    if scale.ndim == 0:
        scale = np.repeat(scale, core_shape[1])

    # extend with zeros
    if scale.shape[0] != core_shape[1]:
        scale = np.pad(scale, (0, core_shape[1] - scale.shape[0]), 'constant', constant_values=(0, 0))

    m0, shift = quant.vconvert_scale_to_shift_and_m0(scale, precision=16)
    int_scale = quant.vconvert_to_fixed_point_int(m0,16)
    scaler_data = scaler_params['output_zp'] * (2**20) + int_scale * (2**4) + (-shift) # Pack into a single word


    # Prepare biases
    biases = scaler_params['gph_node'][0].biases[::-1]
    biases = np.pad(biases, (0, core_shape[1] - biases.shape[0]), 'constant', constant_values=(0, 0))

    print('=== Weight Array ===')
    print(weight_array)

    res_dict = {
        'result': t_res,
        'toeplitz': t_toeplitz,
        'ifmap': ifmap_channel_packed_ints,
        'ifmap_ints': ifmap_channel_minor,
        'small_matrix': t_matrix,
        'matrix': write_array,
        'weights_np': weight_array, 
        'scaler_data': scaler_data,
        'biases': biases,
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
    clip_output = True,
    unsigned_acts = False,
    bitRange = None
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
            # When doing unsigned acts with 1b binary weights, the output tends to oversaturate. We need to make the weights sparse to have testable outputs.
            w = np.random.randint(0,2, wShape)
            if unsigned_acts:
                a = np.random.rand(*wShape)
                w = (a < 0.1).astype(int) # Sparse Weights
        elif weight_mode=='bipolar':
            w = np.random.randint(0,2, wShape)*2-1
        else:
            raise ValueError('Invalid weight_mode')

    if bitRange is None:
        bitRange = xTrits
    if not unsigned_acts:
        low_lim = -(2**(bitRange)-1)
        high_lim = 2**(bitRange)
    else:
        low_lim = 0
        high_lim = 2**(bitRange)

    if x_repeat:
        x = np.random.randint(low_lim, high_lim,wDimY)
        x = x.repeat(xBatches).reshape(wDimY, xBatches).T
    else:
        x = np.random.randint(low_lim, high_lim,xShape)
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