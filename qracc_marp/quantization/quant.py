"""Quantisation utilities — QuantizedTensor, fixed-point conversion, and bit packing."""

from __future__ import annotations

# Transferred in from https://github.com/Lawrence-lugs/eyeriss
# Ended up useful for a bunch of other work

import numpy as np
import pandas as pd
from scipy.signal import convolve2d

df = pd.DataFrame

class QuantizedTensor:
    def __init__(self,shape=None,precision=None,mode='symmetric',real_values=None,quantized_values=None,scale=None,zero_point=None):
        '''
        Quantized Tensor
        Reals are normalized to [-1,1]
        If mode is 'symmetric', zero point is 0 and scale is 2 / (2**precision - 1)

        Parameters:
        shape : tuple -- Shape of the tensor
        precision : int -- Number of bits to quantize to
        mode : str -- Quantization mode, 'symmetric', 'maxmin' or '3sigma'
        real_values : np.ndarray -- Real values of the tensor
        quantized_values : np.ndarray -- Quantized values of the tensor
        scale : float -- Scale of the quantization
        zero_point : float -- Zero point of the quantization
        
        Main attributes:
        real_values : np.ndarray -- Real values of the tensor
        quantized_values : np.ndarray -- Quantized values of the tensor
        scale : float -- Scale of the quantization
        zero_point : float -- Zero point of the quantization
        shape : tuple -- Shape of the tensor
        fake_quantized_values : np.ndarray -- Quantized values translated back to real range
        '''
        if real_values is not None:
            if precision is None:
                raise ValueError('Precision must be provided')
            self.real_values = real_values
            self.quantize(precision,mode,zero_point=zero_point)
            self.dequantize()
        elif quantized_values is not None:
            if scale is None or zero_point is None:
                raise ValueError('Scale and zero point must be provided')
            self.real_values = None
            self.quantized_values = quantized_values
            
            if type(scale) != np.ndarray:
                self.scale = np.array([scale])
            else:
                self.scale = scale

            self.zero_point = zero_point
            self.dequantize()
        else:
            if shape is None or precision is None:
                raise ValueError('Shape and precision must be provided')
            self.real_values = np.random.uniform(-1,1,shape)
            self.quantize(precision,mode)
            self.dequantize()
        self.shape = self.real_values.shape
        return

    def quantize(self, precision, mode='symmetric', zero_point = None, signed=True):
        if mode == 'maxmin' : 
            clip_high = self.real_values.max()
            clip_low = self.real_values.min()
            # self.scale = 2*max(clip_high,clip_low) / (2**precision - 1)
            self.scale = 2*max(clip_high,clip_low) / (2**precision - 1)
            if zero_point is None:
                if not signed:  
                    self.zero_point = 2 ** (precision - 1) - 1
                self.zero_point = 0
            else:
                self.zero_point = zero_point
        elif mode == '3sigma' :
            mean = self.real_values.mean()
            std = self.real_values.std()
            self.scale = std*3 / (2**precision - 1)
            if zero_point is None:
                # if not signed: 
                self.zero_point = 2 ** (precision - 1) - 1
                # self.zero_point = mean / self.scale
            else:
                self.zero_point = zero_point
        elif mode == 'symmetric':
            self.scale = 2 / (2**precision - 1)
            self.zero_point = 0    

        self.scale = np.array([self.scale]) 

        # Clipping
        if signed:
            clip_high = 2 ** (precision - 1) - 1
            clip_low = -2 ** (precision - 1)
        else:
            clip_high = 2 ** precision - 1
            clip_low = 0

        self.quantized_values = np.round( (self.real_values / self.scale) + self.zero_point ).astype(int)
        # self.quantized_values = np.clip(self.quantized_values, clip_low, clip_high)

    def dequantize(self):
        " Creates fake quantization values from the quantized values, like EdMIPS "
        fp_m = self.scale.reshape(self.scale.shape[0],*([1]*(len(self.quantized_values.shape)-1)))
        self.fake_quantized_values = (self.quantized_values - self.zero_point) * fp_m
        if self.real_values is None:
            self.real_values = self.fake_quantized_values
        return self.fake_quantized_values

    def __repr__(self):
        return self.quantized_values.__repr__()

def convolve_fake_quantized(a,w) -> np.ndarray:
    " o = aw "
    return convolve2d(a.fake_quantized_values,w.fake_quantized_values[::-1].T[::-1].T,mode='valid')

def convolve_reals(a,w) -> np.ndarray:
    " o = aw "
    return convolve2d(a.real_values,w.real_values[::-1].T[::-1].T,mode='valid')

def scaling_quantized_matmul(w,a,outBits,internalPrecision,out_scale = None) -> QuantizedTensor:
    " o = w @ a.T but quantized "

    # Matrix multiplication
    qaqw = w.quantized_values @ a.quantized_values.T

    # Scaling
    if out_scale is None:
        out_scale = 2 / (2**outBits - 1)
    newscale = a.scale * w.scale / out_scale
    m0, shift = convert_scale_to_shift_and_m0(
                    newscale,
                    precision=internalPrecision
                )

    fp_m = m0 * 2**(shift)
    # m0bin = convert_to_fixed_point(m0, internalPrecision)
    # m0int = int(m0bin,base=2)

    scaled_clipped_shifted = (qaqw * fp_m).astype(int)
    o_q = saturating_clip(scaled_clipped_shifted, outBits)

    # Quantized tensor of the output
    o_qtensor = QuantizedTensor(
                    qaqw.shape,
                    outBits,
                    quantized_values=o_q,
                    scale=out_scale,
                    zero_point=0 # Assume 0 for now, might be bad later.
                )

    return o_qtensor

def scaling_quantized_convolution(a,w,outBits,internalPrecision, out_scale = None) -> QuantizedTensor:
    " o = a * w but quantized "

    # Convolution
    qaqw = convolve2d(a.quantized_values,w.quantized_values[::-1].T[::-1].T,mode='valid')

    # Scaling
    if out_scale is None:
        out_scale = 2 / (2**outBits - 1)
    newscale = a.scale * w.scale / out_scale
    m0, shift = convert_scale_to_shift_and_m0(
                    newscale,
                    precision=internalPrecision
                )

    fp_m = m0 * 2**(shift)

    # Reals accounting for quantized and fixed point error
    o_q = (qaqw * fp_m).astype(int)
    o_q = saturating_clip(o_q, outBits)

    # Quantized tensor of the output
    o_qtensor = QuantizedTensor(
                    qaqw.shape,
                    outBits,
                    quantized_values=o_q,
                    scale=out_scale,
                    zero_point=0 # Assume 0 for now, might be bad later.
                )

    return o_qtensor
    
def convert_scale_to_shift_and_m0(scale, precision=16):
    """Convert scale(s) to shift and zero point, vectorized."""
    if np.ndim(scale) == 0:
        if scale == 0:
            return np.float64(0.0), np.int64(0)
        shift = int(np.ceil(np.log2(scale)))
        m0 = scale / 2**shift
        mask_one = m0 == 1.0
        if mask_one:
            m0 = 0.9999999999999999
        x = int(np.floor(m0 * (2**precision)))
        m0 = np.float64(x) / (2**precision)
        return m0, np.int64(shift)
    
    scale = np.asarray(scale, dtype=np.float64)
    zero_mask = scale == 0
    shift = np.zeros_like(scale, dtype=np.int64)
    m0 = np.zeros_like(scale, dtype=np.float64)
    
    nonzero = ~zero_mask
    if np.any(nonzero):
        scale_nz = scale[nonzero]
        shift_vals = np.ceil(np.log2(scale_nz)).astype(np.int64)
        shift[nonzero] = shift_vals
        
        pow_shift = np.power(2.0, shift_vals.astype(np.float64))
        m0_raw = scale_nz / pow_shift
        
        mask_one = m0_raw == 1.0
        m0_raw_clamped = m0_raw.copy()
        m0_raw_clamped[mask_one] = 0.9999999999999999
        
        x = np.floor(m0_raw_clamped * (2**precision)).astype(np.int64)
        m0[nonzero] = x.astype(np.float64) / (2**precision)
    
    return m0, shift

vconvert_scale_to_shift_and_m0 = convert_scale_to_shift_and_m0

def convert_to_fixed_point(number, precision):
    """Convert a float (0,1) to fixed point binary string, vectorized."""
    number = np.asarray(number)
    # Handle number == 1 edge case (clamp to 0.999...)
    mask_one = number == 1
    number = number.copy()
    number[mask_one] = 0.9999999999999999
    
    # Compute integer representation
    x = np.floor(number * (2**precision)).astype(np.int64)
    
    # Vectorized binary representation using character operations
    result = np.empty(x.shape, dtype=f'U{precision}')
    for i in range(precision):
        # Extract the i-th bit from the left (MSB first)
        bit = ((x >> (precision - 1 - i)) & 1).astype(str)
        if i == 0:
            result[:] = bit  # Initialize with first bit
        else:
            result = np.char.add(result, bit)  # Append subsequent bits
    
    return result

def convert_to_fixed_point_int(number, precision):
    """Convert a float [0,1] to fixed point binary integer, vectorized."""
    if np.ndim(number) == 0:
        x = number * (2**precision)
        return int(np.floor(x))
    x = number * (2**precision)
    return np.floor(x).astype(np.int64)

vconvert_to_fixed_point_int = convert_to_fixed_point_int

def fixed_point_to_float(number, precision):
    """Convert a fixed point binary string to float [0,1], vectorized."""
    number = np.asarray(number)
    result = np.zeros(number.shape, dtype=np.float64)
    for i in range(precision):
        # Extract the i-th character from each string (vectorized)
        # We can't use np.char.slice (doesn't exist), so iterate over the
        # string array to build per-position character arrays.
        chars = np.array([s[i] for s in number.flat], dtype='U1').reshape(number.shape)
        bit = (chars == '1').astype(np.float64)
        result += bit * (2.0 ** -(i + 1))
    return result

def _right_shift(number, shift):
    """Right shift a number. Shifting rounds toward -infty, vectorized."""
    return np.floor(number / 2.**(shift)).astype(np.int64)

right_shift = _right_shift

def get_array_bits(array,signed=True):
    " Get the number of bits required to represent an array "
    return int(np.ceil(np.log2(np.abs(array).max())))+signed

def _saturating_clip (num_i, inBits=16, outBits=8, signed=True):
    '''
    Saturating clip, vectorized.

    This only implemented saturation before. Now it also clips.
    '''
    num_i_shifted = right_shift(num_i, inBits - outBits)

    if signed:
        min_val = -(2**(outBits-1))
        max_val = 2**(outBits-1)-1
    else:
        min_val = 0
        max_val = 2**outBits-1

    return np.clip(num_i_shifted, min_val, max_val)

saturating_clip = _saturating_clip

def binary_array_to_int(array,signed=False,outBits=None):
    ''' 
    Convert a binary array to an integer 
    The binary array is assumed to be in the last dimension
    [
    [ 0, 1, 1, 0],
    [ 1, 0, 0, 1],
    ...
    ]
    '''
    out = 0
    arr = np.moveaxis(array,-1,0)
    for bit in arr:
        out = (out << 1) | bit
    return out

def array_bin_to_int(array,signed=False,outBits=None):
    shape = array.shape
    pows = np.array([2**i for i in range(shape[-1])])[::-1]
    return np.sum(pows*array,axis=1)

def adc_quantize(partials, adc_bits: int = 4, shift: int = 0,
                 fs_counts: float = None, mode: str = "bipolar") -> np.ndarray:
    """Emulate the flash ADC in ``rtl/ts_qracc.sv`` (fixed full scale).

    The ladder has a *fixed* full-scale range: ``-VDD..+VDD`` in bipolar mode
    and ``0..VDD`` in binary mode, with ``V_RST`` at code 0 in both cases.
    ``numAdcBits`` comparators subdivide that range, so extra comparators buy
    resolution, never range.

    ``shift`` (``cfg.adc_ref_range_shifts``) halves the span *towards* ``V_RST``:
    ``s=1`` gives ``V_RST +- VDD/4``, ``s=2`` gives ``V_RST +- VDD/8``, and so
    on.  In count units the LSB therefore becomes ``2**shift`` times finer and
    the conversion saturates ``2**shift`` times earlier::

        LSB_counts = fs_counts / 2**(adc_bits - 1 + shift)
        code       = clamp(round_half_up(mbl / LSB_counts), ...)

    ``fs_counts`` is the half-span in switch-matrix counts (one conducting row
    = 1) *at* ``shift == 0``.  It is a per-layer parameter: the compiler sets
    the analog full scale to the layer's populated row count / largest partial.
    When omitted it defaults to the code range (``2**(adc_bits-1)``), which is
    the legacy normalisation.

    Parameters
    ----------
    partials : array_like
        Integer partial sums (``mbl_value``) to quantise.
    adc_bits : int
        Comparator count of the flash ADC (RTL default 4).
    shift : int
        ``adc_ref_range_shifts``: halves the span toward ``V_RST`` per step.
    fs_counts : float, optional
        Half-span in counts at ``shift == 0``.
    mode : {"bipolar", "binary"}
        ``"bipolar"`` uses codes ``-2**(n-1) .. 2**(n-1)-1``; ``"binary"``
        clamps to ``0 .. 2**(n-1)-1`` (the ladder half that a unipolar partial
        can reach).

    Returns
    -------
    np.ndarray[int64]
        Quantised codes, same shape as ``partials``.
    """
    p = np.asarray(partials)
    if adc_bits >= 32 and shift == 0 and fs_counts is None:
        return p.astype(np.int64)
    if mode not in ("bipolar", "binary"):
        raise ValueError(f"mode must be 'bipolar' or 'binary', got {mode!r}")
    half = 1 << (adc_bits - 1)
    if fs_counts is None:
        fs_counts = float(half)
    lsb = float(fs_counts) / float(1 << (adc_bits - 1 + shift))
    code = np.floor(p.astype(np.float64) / lsb + 0.5).astype(np.int64)
    if mode == "binary":
        return np.clip(code, 0, half - 1)
    return np.clip(code, -half, half - 1)


def adc_quantize_legacy(partials, adc_bits: int = 4, shift: int = 0) -> np.ndarray:
    """LEGACY ADC transfer function (inverted ``shift`` semantics).

    Kept only so the pre-2026-11-18 captures and ablation numbers stay
    reproducible.  Here ``shift`` *widens* the saturating window to
    ``+/-2**(adc_bits+shift-1)`` and *coarsens* the LSB to ``2**shift``, i.e. a
    digital attenuation rather than the analogue zoom of :func:`adc_quantize`.
    Do not use it for new work.

    Emulate the flash ADC in ``rtl/ts_qracc.sv``.

    ``mbl_value`` (a per-bit-plane partial sum) is compared against the
    saturating window ``[-2**(adc_bits+shift-1), 2**(adc_bits+shift-1)-1]``.
    Inside the window the ADC takes bits ``[shift +: adc_bits]``: round-half-up
    for ``shift > 1`` (the ``doiroundup = mbl[shift-1]`` term) and truncation for
    ``shift == 1``.  Outside the window it saturates to the extreme codes
    ``+/-2**(adc_bits-1)``.  The result is then interpreted as a signed
    ``adc_bits``-bit two's complement code, so code ``2**(adc_bits-1)`` wraps to
    ``-2**(adc_bits-1)`` exactly like the thermometer encoder.

    Parameters
    ----------
    partials : array_like
        Integer partial sums (``mbl_value``) to quantise.
    adc_bits : int
        Comparator count of the flash ADC (RTL default 4).
    shift : int
        ``adc_ref_range_shifts``: the range-shift applied before the ADC.

    Returns
    -------
    np.ndarray[int64]
        Quantised codes, same shape as ``partials``.
    """
    p = np.asarray(partials, dtype=np.int64)
    if adc_bits >= 32 and shift == 0:
        return p
    code_hi = (1 << (adc_bits - 1)) - 1
    code_lo = -(1 << (adc_bits - 1))
    win_hi = (1 << (adc_bits + shift - 1)) - 1
    win_lo = -(1 << (adc_bits + shift - 1))

    over = p > win_hi
    under = p < win_lo
    mid = ~(over | under)

    q = np.zeros_like(p)
    q[over] = code_hi
    q[under] = code_lo

    pm = p[mid]
    if shift == 0:
        qm = pm
    elif shift == 1:
        qm = pm >> 1
    else:
        qm = (pm >> shift) + ((pm >> (shift - 1)) & 1)
    mod = 1 << adc_bits
    half = mod >> 1
    q[mid] = ((qm + half) % mod) - half
    return q


def quantize_int8_to_bits(w_int8: np.ndarray, B: int, signed: bool) -> np.ndarray:
    """Reduce an int8 array to B bits (arithmetic shift), with clamping."""
    if B not in (1, 2, 4, 8):
        raise ValueError(f"B must be in {{1, 2, 4, 8}}, got {B}")
    if B == 8 and signed:
        return w_int8.astype(np.int64)
    if not signed:
        # unsigned only legal for B == 1; legacy binary weights are 0/1
        return (w_int8 != 0).astype(np.int64)
    q = w_int8.astype(np.int64) >> (8 - B)
    min_val = -(2 ** (B - 1))
    max_val = 2 ** (B - 1) - 1
    q = np.clip(q, min_val, max_val)
    return q

def weight_bit_planes(w_int8: np.ndarray, B: int, signed: bool) -> np.ndarray:
    """Return 8 bit-planes of shape (8,)+w_int8.shape. Plane b = (q >> b) & 1 for b < B, else 0."""
    q = quantize_int8_to_bits(w_int8, B, signed)
    planes = np.zeros((8,) + w_int8.shape, dtype=np.uint8)
    for b in range(B):
        planes[b] = ((q >> b) & 1).astype(np.uint8)
    return planes

def int_to_bin(n, bits):
    " Convert an integer to a binary array "
    return np.moveaxis(np.array([n >> i & 1 for i in range(bits-1,-1,-1)]),0,-1)

def int_to_trit(n, trits):
    " Convert an integer to a trit (ternary) array "
    a = int_to_bin(abs(n), trits)
    tritter = (((n < 0) * -2) + 1) # Bipolar array
    tritter = tritter.repeat(trits, axis=n.ndim-1).reshape(a.shape)
    return (a * tritter)

def simulate_trit_mul(w,x, trits, verbose=False, real=True):
    " trit-decomposed multiplication "
    x_trits = int_to_trit(x, trits)
    partials = x_trits.T @ w.T

    if(verbose):
        print('x trits:')
        print(df(x_trits))
        print('partials:')
        print(df(partials.T[::-1].T))

    if real:
        return po2_accumulate_real(partials, verbose=verbose)
    else:
        return po2_accumulate(partials, verbose=verbose)

def po2_accumulate(a,verbose=False):
    " Accumulate an array of powers of 2 "
    acc = np.zeros(a.shape[1])
    print('shifting accumulator:')
    for shift,row in enumerate(a[::-1]):
        acc = acc + row * 2**shift
        if verbose: print(acc)
    return acc

def po2_accumulate_real(a,verbose=False):
    " Accumulate an array of powers of 2 "
    acc = np.zeros(a.shape[1])
    print('shifting accumulator:')
    b = a * 2**(a.shape[0]-1)
    accs = []
    for shift,row in enumerate(b[::-1]):
        acc = acc/2
        acc = acc + row
        accs.append(acc.T[::-1].T.astype(int))
    if verbose: print(df(accs))
    return acc

def fprint_as_hex(
    filepath,
    array,
    elementBits = 8,
    wordSize = 32
    ):

    a = array.flatten()

    with open(filepath, 'w') as f:
        for i in range(0, len(a), wordSize // elementBits):
            hex_str = ''.join([f'{int(x):02x}' for x in a[i:i + wordSize // elementBits]])
            f.write(hex_str + '\n')
        f.write('\n')

    return

def as_packed_hex(
    array,
    elementBits = 8,
    wordSize = 32
    ):
    """
    Convert an array to a packed hex string.
    """
    a = array.flatten()
    chunk_size = wordSize // elementBits
    
    out = []
    for i in range(0, len(a), chunk_size):
        chunk = a[i:i + chunk_size]
        hex_str = ''.join([f'{int(x):02x}' for x in chunk])
        out.append(hex_str)
    
    return np.array(out, dtype=str)