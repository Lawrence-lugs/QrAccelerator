from __future__ import annotations

from dataclasses import dataclass
import pathlib

import numpy as np
import onnx

from qracc_marp.compile import compute
from qracc_marp.compile.stimulus_gen import (
    infer_ofmap_shape,
    infer_optimal_adc_range_shifts,
    infer_bitplane_adc_range_shifts,
    infer_adc_config,

    kernel_to_writes,
    mapped_matrix_to_bank_writes,
    pack_ifmap_to_ints,
    pad_bias_data,
    pad_scaler_writes,
    sample_onnx_qlinearconv,
    vhex3,
    write_input_files,
    write_weight_rows_to_asm,
)
from qracc_marp.constants import (
    CSR_BASE_ADDR_HEX,
    CSR_REG_CHANNELS,
    CSR_REG_CONFIG,
    CSR_REG_IFMAP_DIMS,
    CSR_REG_OFMAP_DIMS,
    CSR_REG_OFFSETS,
    CSR_REG_PADDING,
    CSR_REG_OUTPUT_VIEW,
    CSR_REG_IFMAP_BASE,
    CSR_REG_OFMAP_BASE,
    CSR_REG_WEIGHT,
    DATA_WRITE_ADDR,
    ACTMEM_BYTES,
    ACTMEM_ALIGN,
    ACTMEM_BASE_NONE,
    DEFAULT_CORE_SIZE,
    DWC_CORE_SIZE,
    MASK_1,
    MASK_4,
    MASK_16,
    TRIGGER_ENUM_MAP,
)
from qracc_marp.mapping import core
from qracc_marp.onnx_tools import onnx_utils
import qracc_marp.quantization.quant as quant


def pack_weight_planes(weights, B, signed):
    """Pack per-plane weight bit-words for the B>1 emitter.

    ``weight_bit_planes`` yields 8 planes (b < B real, b >= B zero). Each
    plane is flattened, padded to rows of 32 columns, and each row has its
    columns reversed and is packed MSB-first, so matrix column j ends at word
    bit j (same convention as stimulus_gen.mapped_matrix_to_bank_writes).
    Words are
    returned flat in ``[bank_row, plane]`` order so word index ``i`` maps to
    bank row ``i // 8`` and plane ``i % 8``; planes b >= weight_bits are zero
    words ignored by the shift-add tree (b >= weight_bits_i contributes 0).
    """
    planes = quant.weight_bit_planes(weights, B, signed)
    n_plane = planes.shape[0]
    flat = planes.reshape(n_plane, -1)
    pad = (-flat.shape[1]) % 32
    if pad:
        flat = np.pad(flat, ((0, 0), (0, pad)), constant_values=0)
    rows = flat.reshape(n_plane, -1, 32)
    words = quant.array_bin_to_int(rows.reshape(-1, 32)[:, ::-1])
    words = words.reshape(n_plane, -1).transpose().reshape(-1)
    return words


class QrAccNodeCode(object):
    '''
    Holds all relevant information for testing a single node in QRAcc.
    Mappings and reference output attributes are NCHW
    '''

    def __init__(
        self,
        mapped_node: core.MappedNode,
        mapped_bin: core.MappedBin | None,
        ifmap: np.ndarray,
        imc_core_size: tuple[int, int] = DEFAULT_CORE_SIZE,
        ws_core_size: int = DWC_CORE_SIZE,
        ifmap_bits: int = 8,
        ofmap_bits: int = 8,
        weight_bits: int = 1,
        weight_signed: bool = False,
        nx_model: onnx.ModelProto | None = None,
        ifmap_channel_stride: int | None = None,
        ifmap_channel_offset: int = 0,
        ofmap_channel_stride: int | None = None,
        ofmap_channel_offset: int = 0,
        ifmap_base: int = ACTMEM_BASE_NONE,
        ofmap_base: int = ACTMEM_BASE_NONE,
    ) -> None:

        self.ifmap = ifmap if ifmap.ndim == 4 else ifmap.reshape((1, -1, 1, 1))
        self.ifmap_channel_stride = (
            int(ifmap_channel_stride) if ifmap_channel_stride is not None
            else int(self.ifmap.shape[1])
        )
        self.ifmap_channel_offset = int(ifmap_channel_offset)

        self.ofmap_shape = infer_ofmap_shape(
            ifmap_shape=self.ifmap.shape,
            kernel_shape=mapped_node.kernel.shape,
            pads=mapped_node.pads,
            stride=mapped_node.strides,
        )
        self.ofmap_channel_stride = (
            int(ofmap_channel_stride) if ofmap_channel_stride is not None
            else int(self.ofmap_shape[1])
        )
        self.ofmap_channel_offset = int(ofmap_channel_offset)
        self.ifmap_base = int(ifmap_base)
        self.ofmap_base = int(ofmap_base)

        self.ifmap_bits = ifmap_bits
        self.ofmap_bits = ofmap_bits
        self.weight_bits = weight_bits
        self.weight_signed = weight_signed

        self.ws_core_size = ws_core_size
        self.imc_core_size = imc_core_size

        self.mapped_bin = mapped_bin
        self.mapped_node = mapped_node

        if nx_model is None:
            self.reference_output = self._generate_reference_output()[0].transpose((0, 2, 3, 1))  # Convert to NHWC format
        else:
            output_tensor = mapped_node.nx_node.output[0]
            input_dict = self._get_input_dict()
            onnx_out = onnx_utils.get_intermediate_tensor_value(nx_model,output_tensor,input_dict=input_dict)

            # We pretend the output is in NCHW if it's a matmul (we treat those like pointwise convs)
            if len(onnx_out.shape) == 1:
                onnx_out = onnx_out.reshape((1, -1, 1, 1))
            self.reference_output = onnx_out.transpose((0, 2, 3, 1))
        
        self.toeplitz = compute.toeplitzize_input(
            in_tensor = self.ifmap.squeeze(axis=0), # Remove batch dimension for toeplitz
            kernel_shape=mapped_node.kernel.shape,
            strides=mapped_node.strides,
            pads=mapped_node.pads,
            zero_point=mapped_node.x_zp,
            channel_minor=False
        )

        self.nx_model = nx_model

        # The writable matrix is the kernel for depthwise nodes, because they go into qracc
        self.matrix = mapped_node.matrix if not mapped_node.depthwise else mapped_node.kernel

        self.inputs = self.mapped_node.get_true_inputs()  # Non-initializer inputs of the node
        self.outputs = self.mapped_node.nx_node.output

        return
    
    def _get_input_dict(self):
        if self.mapped_node.type == 'QLinearMatMul':
            in_tensor = self.ifmap.squeeze()  # Convert to a 1D tensor for matmul
        else:
            in_tensor = self.ifmap
        input_dict = {
            self.mapped_node.nx_node.input[0]: in_tensor,
        }
        return input_dict

    
    def config(self):
        '''
        Returns the configuration for the QRAcc node.
        '''

        ifmap_shape = self.ifmap.shape
        mapped_node = self.mapped_node
        ifmap_bits = self.ifmap_bits
        ofmap_bits = self.ofmap_bits

        if not mapped_node.depthwise:
            if ifmap_shape[1] != mapped_node.kernel.shape[1]:
                raise ValueError(f"Input feature map channels {ifmap_shape} do not match kernel input channels {mapped_node.kernel.shape}.")

        kernel_shape = mapped_node.kernel.shape
        # ofmap_dimx = ((ifmap_shape[2] - kernel_shape[2] + 2*mapped_node.pads[0]) // mapped_node.strides[0]) + 1 #(W-K+2P)/S + 1
        # ofmap_dimy = ((ifmap_shape[3] - kernel_shape[3] + 2*mapped_node.pads[1]) // mapped_node.strides[1]) + 1

        ofmap_dimx = self.ofmap_shape[2]
        ofmap_dimy = self.ofmap_shape[3]


        if mapped_node.depthwise:
            # Depthwise nodes run on the WSAcc path; the IMC ADC settings are
            # irrelevant, keep the historical defaults.
            adc_cfg = {"bits": 4, "s": 0, "fs_counts": None,
                       "lsb_counts": None, "clip_frac": 0.0,
                       "snr_db": None, "preview": {}}
            ladder = "binary"
        else:
            # Fixed full-scale flash ADC: `s` halves the span toward V_RST, so
            # the chooser trades range against resolution (see
            # PLAN_adc_range_model_correction.md).  Multi-bit weights use the
            # bipolar switch matrix (NSM driven with the inverted activation).
            ladder = "bipolar" if self.weight_bits > 1 else "binary"
            # The ADC full scale is fixed by the analog reference to the
            # maximum possible |mbl| of a fully loaded bank (numRows counts).
            # Only s is a runtime range selection.  s is a natural number, not
            # a 2-bit field: s<=8 is the realistic limit for an ADC that still
            # fits beside the memory banks (below that the LSB approaches the
            # ~16 mVrms comparator noise floor).
            adc_cfg = infer_adc_config(
                toeplitz_acts=self.toeplitz,
                weights=mapped_node.matrix,
                ifmap_bits=ifmap_bits,
                weight_bits=self.weight_bits,
                adc_bits=getattr(self, "adc_bits", 4),
                ladder=ladder,
                fs_counts=float(self.imc_core_size[0]),
                s_max=8,
            )
        adc_ref_range_shifts = int(adc_cfg["s"])
        self.adc_config = adc_cfg

        config_dict = {
            "n_input_bits_cfg": ifmap_bits,
            "n_output_bits_cfg": ofmap_bits,
            "unsigned_acts": 1,
            "binary_cfg": 1 if ladder == "binary" else 0,
            "adc_ref_range_shifts": int(adc_ref_range_shifts),
            "filter_size_y": kernel_shape[3],
            "filter_size_x": kernel_shape[2],
            "input_fmap_dimx": ifmap_shape[2],
            "input_fmap_dimy": ifmap_shape[3],
            "output_fmap_dimx": ofmap_dimx,
            "output_fmap_dimy": ofmap_dimy,
            "stride_x": mapped_node.strides[0],
            "stride_y": mapped_node.strides[1],
            "num_input_channels": ifmap_shape[1],
            "num_output_channels": kernel_shape[0],
            "ifmap_channel_stride": self.ifmap_channel_stride,
            "ifmap_channel_offset": self.ifmap_channel_offset,
            "ofmap_channel_stride": self.ofmap_channel_stride,
            "ofmap_channel_offset": self.ofmap_channel_offset,
            "ifmap_base": self.ifmap_base,
            "ofmap_base": self.ofmap_base,
            "mapped_matrix_offset_x": mapped_node.offset_x,
            "mapped_matrix_offset_y": mapped_node.offset_y,
            "padding": mapped_node.pads[0],  # Use 0 padding for soft padding
            "padding_value": mapped_node.x_zp,  # Padding value for the input feature map
            "weight_bits": int(self.weight_bits),
            "weight_signed": int(bool(self.weight_signed)),
        }

        return config_dict
    
    @classmethod
    def produce_single_node_test(
        cls,
        ifmap_shape,
        kernel_shape,
        pads,
        stride,
        depthwise,
        offset_x,
        offset_y,
        core_size,
        ws_core_size,
        ifmap_bits = 8,
        kernel_bits = 1
    ):
        
        nx_node, nx_model, ifmap = sample_onnx_qlinearconv(ifmap_shape=ifmap_shape,ifmap_bits=ifmap_bits,kernel_shape=kernel_shape,kernel_bits=kernel_bits,kernel_dtype = np.int8,pads = pads,stride = stride, seed = 0, depthwise = depthwise)

        mapped_node = core.MappedNode(nx_node, bin_id = 0, mapped_rect=None, nx_model = nx_model, offset_x=offset_x, offset_y = offset_y)

        bin_weights = np.zeros(core_size, dtype=np.int8)
        bin_weights[offset_y:offset_y+mapped_node.matrix.shape[0], offset_x:offset_x+mapped_node.matrix.shape[1]] = mapped_node.matrix

        mapped_bin = core.MappedBin(
            bin_id = 0,
            weights = bin_weights
        )

        u_code = QrAccNodeCode(
            mapped_node = mapped_node,
            mapped_bin = mapped_bin,
            ifmap = ifmap,
            imc_core_size = core_size,
            ws_core_size = ws_core_size,
            nx_model = nx_model,
        )

        return u_code
    
    def _get_weight_data(self):
        if self.mapped_node.depthwise:

            if self.mapped_node.kernel.shape[0] < self.ws_core_size:
                physical_kernel = np.zeros((self.ws_core_size, *self.mapped_node.kernel.shape[1:]), dtype=self.mapped_node.kernel.dtype)
                physical_kernel[:self.mapped_node.kernel.shape[0]] = self.mapped_node.kernel
            else:
                physical_kernel = self.mapped_node.kernel

            physical_kernel_hwc = physical_kernel.transpose(1,2,3,0)  # Convert to KHWC format
            return kernel_to_writes(physical_kernel_hwc, channels=self.ws_core_size, hexes=False)
        else:
            if self.weight_bits > 1:
                return pack_weight_planes(self.mapped_bin.weights, B=self.weight_bits, signed=self.weight_signed)
            return mapped_matrix_to_bank_writes(self.mapped_bin.weights, 32)
        
    @property
    def rtl_publishes_2x(self):
        """True when seq_acc publishes 2*MAC instead of MAC.

        The analog multibit path uses the bipolar ladder and signed weights:
        seq_acc removes the activation bias and leaves the factor 2 from
        ``mbl = 2P - A_j``.  The output scaler must therefore be calibrated for
        ``2*MAC``: scale is halved and the bias is doubled, so
        ``(2*MAC + 2*bias) * (scale/2) == (MAC + bias) * scale``.
        """
        return (not self.mapped_node.depthwise
                and self.weight_bits > 1
                and bool(self.weight_signed))

    def _get_scaler_data(self):
        scale = np.asarray(self.mapped_node.scale, dtype=np.float64)
        s = int(getattr(self, 'adc_config', {}).get('s', 0))
        if self.rtl_publishes_2x:
            # seq_acc publishes (2*MAC) << s and the B-bit weight planes use
            # q, not q*2**(8-B): restore all three factors in the scale.
            scale = scale * 0.5 * (2 ** (8 - self.weight_bits)) / (2 ** s)
        elif not self.mapped_node.depthwise:
            # Binary analog seq_acc publishes acc << s (no 2x, no B shift).
            scale = scale / (2 ** s)
        return pad_scaler_writes(
            scale_to_map = scale,
            core_shape= self.imc_core_size,
            output_zero_point = self.mapped_node.y_zp,
            mm_offset_x= self.mapped_node.offset_x,
        )
    
    def _get_bias_data(self):
        biases = np.asarray(self.mapped_node.biases).astype(np.int64)
        s = int(getattr(self, 'adc_config', {}).get('s', 0))
        if self.rtl_publishes_2x:
            # mapped_node.biases already folds -x_zp*sum(raw kernel).  The
            # hardware uses the B-bit weights q, so re-fold with sum(q):
            # bias_B = bias_raw - x_zp*sum(q).
            raw_bias = biases + int(self.mapped_node.x_zp) * self.mapped_node.kernel.sum(
                axis=(1, 2, 3), dtype=np.int64)
            w_B = quant.quantize_int8_to_bits(
                self.mapped_node.kernel, self.weight_bits, signed=True)
            bias_B = raw_bias - int(self.mapped_node.x_zp) * w_B.sum(
                axis=(1, 2, 3), dtype=np.int64)
            # seq_acc publishes (2*MAC) << s.  The scaler adds this bias after
            # that shift, so it must be pre-shifted by s as well.
            biases = bias_B * 2 * (2 ** s)
        elif not self.mapped_node.depthwise:
            # Binary analog path: acc << s.
            biases = biases * (2 ** s)
        return pad_bias_data(biases,
            core_shape=self.imc_core_size, 
            mm_offset_x=self.mapped_node.offset_x,
        )
    
    def _get_ifmap_data(self):
        ifmap_hwc = self.ifmap.transpose(0,2,3,1)
        return pack_ifmap_to_ints(ifmap_hwc)

    def write_files(self, savepath):
        '''
        Write reference text files for the QRAcc RTL testbench.
        Optional. Only used to debug.
        '''
        
        res_dict = {
            'result': self.reference_output,
            'toeplitz': self.toeplitz,
            'ifmap': self.ifmap.transpose(0,2,3,1),  # Convert to NHWC format
            'matrix_raw': self.matrix,  
            'scaler_data': self._get_scaler_data(),
            'biases': self._get_bias_data()
        }

        write_input_files(res_dict, savepath)

    def _generate_reference_output(self):
        node_initializers = [
            self.ifmap,
            self.mapped_node.x_scale,
            self.mapped_node.x_zp,
            self.mapped_node.kernel,
            self.mapped_node.w_scale,
            self.mapped_node.w_zp,
            self.mapped_node.y_scale,
            self.mapped_node.y_zp,
            self.mapped_node.biases
        ]
        sample_outs = np.random.randint(
            low=0, high=2**self.ofmap_bits, size=self.ofmap_shape, dtype=np.uint8
        )
        return onnx_utils.infer_node_output(
            self.mapped_node.nx_node,
            inputs=node_initializers,
            outputs=[sample_outs],
            name=self.mapped_node.name,
        )        
    
    def compile(
        self,
        include_ifmap_writes: bool = True,
        write_weights: bool = True,
        add_read: bool = True,
        config_write_address: str = CSR_BASE_ADDR_HEX,
        end: bool = True,
        preserve_ifmap: bool = False,
    ) -> list[str]:
        '''
        Compile the node into a list of assembly instructions for QRAcc.
        include_ifmap_writes: bool, whether to include ifmap writes in the output.
        solo: bool, whether to compile the node as a standalone unit (default True).
        '''
        # print(f"Compiling node {self.mapped_node.node_id}:{self.mapped_node.name} for QRAcc...")

        config_dict = self.config()
        config_writes = bundle_config_into_write(config_dict, config_write_address)
        commands = config_writes
        
        if write_weights:
            if self.mapped_node.depthwise:
                commands += make_trigger_write('TRIGGER_LOADWEIGHTS_DIGITAL', write_address=config_write_address)
            else:
                commands += make_trigger_write('TRIGGER_LOADWEIGHTS', write_address=config_write_address)
            if self.weight_bits > 1:
                commands += write_weight_rows_to_asm(self._get_weight_data(), signed=False)
            else:
                commands += write_array_to_asm(self._get_weight_data()) 
        
        # Writing to the scaler is not optional
        commands += make_trigger_write('TRIGGER_LOAD_SCALER', write_address=config_write_address)
        commands += write_array_to_asm(self._get_scaler_data()) 
        commands += write_array_to_asm(self._get_bias_data()) 
        
        if include_ifmap_writes: # If not, the ifmap is assumed to be already in the ACTMEM
            commands += make_trigger_write('TRIGGER_LOAD_ACTIVATION', write_address=config_write_address)
        commands += write_array_to_asm(self._get_ifmap_data())

        if self.mapped_node.depthwise:
            commands += make_trigger_write('TRIGGER_COMPUTE_DIGITAL', write_address=config_write_address, preserve_ifmap=preserve_ifmap)
        else:
            commands += make_trigger_write('TRIGGER_COMPUTE_ANALOG', write_address=config_write_address, preserve_ifmap=preserve_ifmap)
        commands += [f'WAITBUSY']
        
        if add_read:
            commands += make_trigger_write('TRIGGER_READ_ACTIVATION', write_address=config_write_address)
            commands += [f'WAITREAD']
            if end:
                commands += ['END']

        return commands
    
    def __repr__(self):
        # Print attributes of the class, showing shapes for arrays
        attrs = vars(self)
        attr_strs = []
        for key, value in attrs.items():
            if isinstance(value, np.ndarray):
                attr_strs.append(f"{key}=array(shape={value.shape})")
            elif key == 'mapped_node':
                attr_strs.append(f"{key}={value.name} (id={value.node_id})")
            elif key == 'mapped_bin' and value is not None:
                attr_strs.append(f"{key}={value.bin_id} (shape={value.weights.shape})")
            elif key == 'nx_model':
                attr_strs.append(f"{key}={value.graph.name} (nodes={len(value.graph.node)})")
            else:
                attr_strs.append(f"{key}={value}")
        attr_list = ',\n\t'.join(attr_strs)
        return f"QrAccNodeCode(\n\t{attr_list})"

def generate_intermediate_tensor(
    nx_model : onnx.ModelProto,
    node_id : int,
    input_dict : dict,
    real : bool = False,
):
    """Return the node input tensor.

    ``real=False`` preserves the historical random-ifmap behaviour.  For an
    end-to-end run use ``real=True``: ONNX Runtime computes the actual
    intermediate tensor from the supplied model input.
    """
    input_name = nx_model.graph.node[node_id].input[0]
    value = onnx_utils.get_intermediate_tensor_value(
        nx_model, input_name, input_dict=input_dict)
    if real:
        return value
    return np.random.randint(0, 256, value.shape).astype(np.uint8)


def generate_random_intermediate_tensor(*args, **kwargs):
    """Backward-compatible alias for :func:`generate_intermediate_tensor`."""
    return generate_intermediate_tensor(*args, **kwargs)

def is_nx_node_compilable(
    nx_node : onnx.NodeProto
):
    """
    Check if an ONNX node is compilable for QRAcc.
    Currently, only QLinearConv and QLinearMatMul nodes are supported.
    """
    if nx_node is None:
        return False
    if nx_node.op_type == 'QLinearConv':
        return True
    elif nx_node.op_type == 'QLinearMatMul':
        return True
    else:
        return False

def make_trigger_write(
    command: str,
    clear: int = 0,
    inst_write_mode: int = 0,
    csr_main_trigger_enum: dict[str, int] | None = None,
    write_address: str = CSR_BASE_ADDR_HEX,
    preserve_ifmap: bool = False,
) -> list[str]:
    """Build a single LOAD instruction that writes a trigger word to the CSR.

    Args:
        command: Trigger name (e.g. ``'TRIGGER_COMPUTE_ANALOG'``).
        clear: Clear bit (0 or 1).
        inst_write_mode: Instruction write-mode bit.
        csr_main_trigger_enum: Optional custom trigger→value mapping.
        write_address: Hex-string target address.
        preserve_ifmap: If *True* the ifmap is kept in ACTMEM.
    """
    if csr_main_trigger_enum is None:
        csr_main_trigger_enum = TRIGGER_ENUM_MAP
    if command not in csr_main_trigger_enum:
        raise ValueError(f"Unknown command: {command}")

    trigger_val = csr_main_trigger_enum[command] & 0x7
    clear_val = (clear & MASK_1) << 3
    inst_write_mode_val = (inst_write_mode & MASK_1) << 5
    preserve_ifmap_val = (int(preserve_ifmap) & MASK_1) << 12

    word = trigger_val | clear_val | inst_write_mode_val | preserve_ifmap_val
    return [f'LOAD {write_address} {word:08x}']

def bundle_config_into_write(
    config_dict: dict[str, int],
    config_write_address: str = CSR_BASE_ADDR_HEX,
) -> list[str]:
    """Pack QRAcc configuration fields into seven 32-bit CSR LOAD instructions."""
    base_addr = int(config_write_address, 16)

    config_word = (
        ((config_dict['n_output_bits_cfg']      & MASK_4) << 28) |
        ((config_dict['n_input_bits_cfg']       & MASK_4) << 24) |
        ((config_dict['stride_y']               & MASK_4) << 20) |
        ((config_dict['stride_x']               & MASK_4) << 16) |
        ((config_dict['filter_size_x']          & MASK_4) << 12) |
        ((config_dict['filter_size_y']          & MASK_4) << 8)  |
        ((config_dict['adc_ref_range_shifts']   & MASK_4) << 4)  |
        ((config_dict['unsigned_acts']          & MASK_1) << 1)  |
        ((config_dict['binary_cfg']             & MASK_1) << 0)
    )
    ifmap_dims_word = (
        ((config_dict['input_fmap_dimy'] & MASK_16) << 16) |
        ((config_dict['input_fmap_dimx'] & MASK_16) << 0)
    )
    ofmap_dims_word = (
        ((config_dict['output_fmap_dimy'] & MASK_16) << 16) |
        ((config_dict['output_fmap_dimx'] & MASK_16) << 0)
    )
    channels_word = (
        ((config_dict['num_output_channels'] & MASK_16) << 16) |
        ((config_dict['num_input_channels']  & MASK_16) << 0)
    )
    offsets_word = (
        ((config_dict['mapped_matrix_offset_y'] & MASK_16) << 16) |
        ((config_dict['mapped_matrix_offset_x'] & MASK_16) << 0)
    )
    padding_word = (
        ((int(config_dict['padding_value']) & MASK_16) << 4) |
        ((config_dict['padding'] & MASK_16) << 0)
    )
    weight_word = (
        ((config_dict.get('weight_bits', 1) & 0xF) << 0) |
        ((config_dict.get('weight_signed', 0) & 0x1) << 4) |
        ((config_dict.get('ifmap_channel_stride', 0) & 0xFFFF) << 5) |
        ((config_dict.get('ifmap_channel_offset', 0) & 0xFF) << 21)
    )
    output_view_word = (
        ((config_dict.get('ofmap_channel_stride', 0) & 0xFFFF) << 0) |
        ((config_dict.get('ofmap_channel_offset', 0) & 0xFFFF) << 16)
    )
    ifmap_base_word = config_dict.get('ifmap_base', ACTMEM_BASE_NONE) & 0xFFFFFFFF
    ofmap_base_word = config_dict.get('ofmap_base', ACTMEM_BASE_NONE) & 0xFFFFFFFF

    config_writes = [
        f"LOAD {base_addr + CSR_REG_CONFIG:08x} {config_word:08x}",
        f"LOAD {base_addr + CSR_REG_IFMAP_DIMS:08x} {ifmap_dims_word:08x}",
        f"LOAD {base_addr + CSR_REG_OFMAP_DIMS:08x} {ofmap_dims_word:08x}",
        f"LOAD {base_addr + CSR_REG_CHANNELS:08x} {channels_word:08x}",
        f"LOAD {base_addr + CSR_REG_OFFSETS:08x} {offsets_word:08x}",
        f"LOAD {base_addr + CSR_REG_PADDING:08x} {padding_word:08x}",
        f"LOAD {base_addr + CSR_REG_WEIGHT:08x} {weight_word:08x}",
        f"LOAD {base_addr + CSR_REG_OUTPUT_VIEW:08x} {output_view_word:08x}",
        f"LOAD {base_addr + CSR_REG_IFMAP_BASE:08x} {ifmap_base_word:08x}",
        f"LOAD {base_addr + CSR_REG_OFMAP_BASE:08x} {ofmap_base_word:08x}",
    ]

    return config_writes

def write_array_to_asm(write_array: np.ndarray | list, address: str = DATA_WRITE_ADDR) -> list[str]:
    """Convert a data array into a list of LOAD assembly instructions."""
    asm = []
    for element in write_array:
        asm.append(f"LOAD {address} {vhex3(element)}")
    return asm

def get_config_from_mapped_node(
    mapped_node : core.MappedNode,
    ifmap_shape : tuple,
    ifmap_bits = 8,
    ofmap_bits = 8,
    weight_bits = 8
):
    '''
    Generate QRAcc configuration for a QLinearConv node.
    Needs information about the previous ifmap shape.
    '''

    if ifmap_shape[1] != mapped_node.kernel.shape[1]:
        raise ValueError("Input feature map channels do not match kernel input channels.")

    kernel_shape = mapped_node.kernel.shape
    ofmap_dimx = ((ifmap_shape[2] - kernel_shape[2] + 2*mapped_node.pads[0]) // mapped_node.strides[0]) + 1 #(W-K+2P)/S + 1
    ofmap_dimy = ((ifmap_shape[3] - kernel_shape[3] + 2*mapped_node.pads[1]) // mapped_node.strides[1]) + 1

    tplitz_window_length = kernel_shape[2] * kernel_shape[3] * ifmap_shape[1] # CFxFy

    tplitz_act_vector = np.random.randint(
        low=0, high=2**ifmap_bits, size=tplitz_window_length)

    adc_ref_range_shifts = infer_optimal_adc_range_shifts(
        tplitz_act_vector=tplitz_act_vector,
        weights=mapped_node.matrix,
        ifmap_bits=ifmap_bits,
        weight_bits=weight_bits
    )

    config_dict = {
        "n_input_bits_cfg": ifmap_bits,
        "n_output_bits_cfg": ofmap_bits,
        "unsigned_acts": 1,
        "binary_cfg": 1,
        "adc_ref_range_shifts": int(adc_ref_range_shifts),
        "filter_size_y": kernel_shape[3],
        "filter_size_x": kernel_shape[2],
        "input_fmap_dimx": ifmap_shape[2],
        "input_fmap_dimy": ifmap_shape[3],
        "output_fmap_dimx": ofmap_dimx,
        "output_fmap_dimy": ofmap_dimy,
        "stride_x": mapped_node.strides[0],
        "stride_y": mapped_node.strides[1],
        "num_input_channels": ifmap_shape[1],
        "num_output_channels": kernel_shape[0],
        "ifmap_channel_stride": ifmap_shape[1],
        "ifmap_channel_offset": 0,
        "mapped_matrix_offset_x": mapped_node.offset_x,
        "mapped_matrix_offset_y": mapped_node.offset_y,
        "padding": mapped_node.pads[0],  # Use 0 padding for soft padding
        "padding_value": mapped_node.x_zp,  # Padding value for the input feature map
    }

    return config_dict

def check_if_any_consumers_are_noncompilable(
    nx_model : onnx.ModelProto,
    nx_node : int
):
    """
    Check if any consumers of the given node are non-compilable.
    Returns True if any consumer is non-compilable, False otherwise.
    """
    for output in nx_node.output:
        for node in nx_model.graph.node:
            if output in node.input and not is_nx_node_compilable(node):
                return True
    return False

def _producer_index(nx_model, tensor_name):
    for idx, node in enumerate(nx_model.graph.node):
        if tensor_name in node.output:
            return idx
    return None


def _resolve_channel_slice(nx_model, input_name):
    """Return (parent_tensor, channel_offset, slice_channels) for a Slice.

    Only channel-axis slices (axis 1) are treated as an internal ACTMEM view.
    Other Slice layouts fall back to the original input tensor.
    """
    for node in nx_model.graph.node:
        if node.op_type != 'Slice' or input_name not in node.output:
            continue
        try:
            starts = np.asarray(
                onnx.numpy_helper.to_array(
                    next(i for i in nx_model.graph.initializer
                         if i.name == node.input[1])).flatten())
            ends = np.asarray(
                onnx.numpy_helper.to_array(
                    next(i for i in nx_model.graph.initializer
                         if i.name == node.input[2])).flatten())
            axes = np.asarray(
                onnx.numpy_helper.to_array(
                    next(i for i in nx_model.graph.initializer
                         if i.name == node.input[3])).flatten())
        except StopIteration:
            return input_name, 0, None
        if axes.size == 1 and int(axes[0]) == 1:
            offset = int(starts[0])
            channels = int(ends[0] - starts[0])
            return node.input[0], offset, channels
    return input_name, 0, None


def _next_compilable_input(nx_model, start_index, until):
    for idx in range(start_index + 1, until):
        node = nx_model.graph.node[idx]
        if is_nx_node_compilable(node):
            parent, _, _ = _resolve_channel_slice(nx_model, node.input[0])
            return idx, parent
    return None, None


@dataclass
class InternalConcatView:
    """Compiler-side plan for one channel-axis Concat."""

    output: str
    inputs: tuple[str, ...]
    channels: tuple[int, ...]
    offsets: tuple[int, ...]
    total_channels: int
    height: int
    width: int
    producer_ids: tuple[int, ...]
    parent_bytes: int
    output_bytes: int
    live_bytes: int
    supported: bool
    reason: str = ""

    def offset_for(self, tensor_name: str) -> int | None:
        try:
            return self.offsets[self.inputs.index(tensor_name)]
        except ValueError:
            return None


def _shape_of_tensor(nx_model, name, cache):
    if name in cache:
        return cache[name]
    candidates = list(nx_model.graph.input) + list(nx_model.graph.output)
    candidates += list(nx_model.graph.value_info)
    for vi in candidates:
        if vi.name != name:
            continue
        dims = []
        for d in vi.type.tensor_type.shape.dim:
            if not d.HasField('dim_value'):
                cache[name] = None
                return None
            dims.append(int(d.dim_value))
        cache[name] = tuple(dims)
        return cache[name]
    cache[name] = None
    return None


@dataclass(frozen=True)
class SlotAllocation:
    """One byte range assigned to a non-aliased tensor slot."""

    name: str
    base: int
    bytes: int
    first: int
    last: int


@dataclass(frozen=True)
class TensorView:
    """Physical layout of a tensor in ACTMEM."""

    tensor: str
    backing: str
    shape: tuple[int, ...] | None
    bytes: int
    pixel_stride: int
    channel_offset: int
    role: str = "tensor"


@dataclass
class ResidentRegion:
    """A DAG of nodes scheduled without leaving ACTMEM."""

    node_ids: tuple[int, ...]
    entries: tuple[str, ...]
    exits: tuple[str, ...]
    views: tuple[TensorView, ...]
    peak_live_bytes: int
    supported: bool
    reason: str = ""
    slots: tuple[tuple[str, int, int, int], ...] = ()
    allocations: tuple[SlotAllocation, ...] = ()


@dataclass
class RegionPlan:
    """Compiler-side region schedule plus its memory/layout evidence."""

    regions: tuple[ResidentRegion, ...]

    @property
    def supported(self) -> bool:
        return all(r.supported for r in self.regions)

    @property
    def peak_live_bytes(self) -> int:
        return max((r.peak_live_bytes for r in self.regions), default=0)


def _resolve_shape(nx_model, u_nx_mapping, name, cache, in_progress=None):
    """Resolve a tensor shape through pass-through/split/view producers."""
    if name in cache:
        return cache[name]
    in_progress = in_progress or set()
    if name in in_progress:
        return None
    in_progress.add(name)
    s = _shape_of_tensor(nx_model, name, cache)
    if s is not None:
        return s
    p = _producer_index(nx_model, name)
    if p is None:
        return None
    node = nx_model.graph.node[p]
    try:
        mn = u_nx_mapping.get_mapped_node_by_id(p)
    except ValueError:
        mn = None
    if mn is not None:
        parent, _, nch = _resolve_channel_slice(nx_model, mn.nx_node.input[0])
        ps = _resolve_shape(nx_model, u_nx_mapping, parent, cache, in_progress)
        if ps is None or len(ps) != 4:
            return None
        in_shape = (1, int(nch) if nch else ps[1], ps[2], ps[3])
        try:
            out = infer_ofmap_shape(
                ifmap_shape=in_shape, kernel_shape=mn.kernel.shape,
                pads=mn.pads, stride=mn.strides)
        except Exception:
            return None
        cache[name] = tuple(out)
        return tuple(out)
    # Non-compilable pass-through (QuantizeLinear) or channel Slice.  For a
    # Slice, the tensor being resolved is the Slice *output*, so resolve its
    # own output name rather than its input.
    slice_parent, _, nch = _resolve_channel_slice(nx_model, name)
    parent = slice_parent if nch is not None else node.input[0]
    ps = _resolve_shape(nx_model, u_nx_mapping, parent, cache, in_progress)
    if ps is None or len(ps) != 4:
        return None
    out = (1, int(nch), ps[2], ps[3]) if nch else ps
    cache[name] = out
    return out


def _allocate_slots(slots, capacity, entry_names=()):
    """First-fit byte allocator with liveness-based slot reuse.

    Slots are intervals over the region schedule.  A slot is placed in the
    lowest free range that does not overlap a still-live allocation.  Aliased
    view slots are not passed here.  Entry tensors are placed first because
    the external loader writes them at the region base (address 0 in the
    current LOADACTS path).
    """
    entry_names = set(entry_names)
    allocations = []
    active = []
    # Entries and short-lived slots at the same schedule point are placed
    # before long-lived outputs, so an external entry remains at its load
    # address instead of being overwritten by its first producer output.
    for name, nbytes, first, last in sorted(
            slots, key=lambda s: (
                s[2], 0 if s[0] in entry_names else 1, s[3], -s[1], s[0])):
        if nbytes <= 0:
            continue
        active = [(b, e, s_last, n) for b, e, s_last, n in active
                  if s_last >= first]
        base = 0
        for b, e, _, _ in sorted(active):
            if base + nbytes <= b:
                break
            base = max(base, e)
        base = ((base + ACTMEM_ALIGN - 1) // ACTMEM_ALIGN) * ACTMEM_ALIGN
        if base + nbytes > capacity:
            return tuple(allocations), (
                f'slot {name} needs {nbytes} B at base {base}, '
                f'exceeds {capacity} B')
        allocations.append(SlotAllocation(name, base, nbytes, first, last))
        active.append((base, base + nbytes, last, name))
    return tuple(allocations), ''


def _build_region_plan_once(nx_model, u_nx_mapping, concat_views,
                            starting, until, capacity=ACTMEM_BYTES):
    """Build the current DAG-region view without changing command emission.

    This is Phase R1 of the region scheduler: it exposes region/entry/exit/view
    metadata and a full live-range budget while the existing traverse loop keeps
    emitting the validated MBV2 command stream.
    """
    shape_cache = {}
    regions = []
    run = []
    run_nodes = set()

    def close_run():
        if not run:
            return
        comp = [i for i in run if is_nx_node_compilable(nx_model.graph.node[i])]
        if not comp:
            run.clear(); run_nodes.clear(); return
        # Entries: true inputs with no producer inside this region.
        init_names = {i.name for i in nx_model.graph.initializer}
        entries = []
        for i in comp:
            node = nx_model.graph.node[i]
            for inp in node.input:
                if inp in init_names:
                    continue
                p = _producer_index(nx_model, inp)
                if p is None or p not in run_nodes:
                    if inp not in entries:
                        entries.append(inp)
        # Exits: outputs with an outside consumer or graph-output status.
        exits = []
        outputs = set(nx_model.graph.output[i].name
                      for i in range(len(nx_model.graph.output)))
        for i in comp:
            for out in nx_model.graph.node[i].output:
                consumers = [j for j, n in enumerate(nx_model.graph.node)
                             if out in n.input]
                if out in outputs or any(j not in run_nodes for j in consumers):
                    if out not in exits:
                        exits.append(out)

        views = []
        for i in run:
            node = nx_model.graph.node[i]
            if node.op_type == 'Slice' and node.output:
                parent, off, nch = _resolve_channel_slice(
                    nx_model, node.output[0])
                ps = _resolve_shape(
                    nx_model, u_nx_mapping, parent, shape_cache)
                if (nch is not None and ps is not None and len(ps) == 4):
                    views.append(TensorView(
                        tensor=node.output[0], backing=parent,
                        shape=(1, int(nch), ps[2], ps[3]), bytes=0,
                        pixel_stride=ps[1], channel_offset=off,
                        role='slice'))
            if node.op_type == 'Concat' and node.output:
                view = concat_views.get(node.output[0])
                if view is not None and view.supported:
                    views.append(TensorView(
                        tensor=view.output, backing=view.output,
                        shape=(1, view.total_channels, view.height, view.width),
                        bytes=view.total_channels * view.height * view.width,
                        pixel_stride=view.total_channels, channel_offset=0,
                        role='concat_group'))
                    for name, off in zip(view.inputs, view.offsets):
                        views.append(TensorView(
                            tensor=name, backing=view.output,
                            shape=(1, view.channels[view.inputs.index(name)],
                                   view.height, view.width),
                            bytes=0, pixel_stride=view.total_channels,
                            channel_offset=off, role='concat_slice'))
        # Slots are non-aliased tensors: entries, normal outputs, and groups.
        slot_bytes = {}
        slot_first = {}
        slot_last = {}
        positions = {node_id: pos for pos, node_id in enumerate(comp)}
        for name in entries:
            s = _resolve_shape(nx_model, u_nx_mapping, name, shape_cache)
            if s is not None and len(s) == 4:
                slot_bytes[name] = int(s[1] * s[2] * s[3])
                slot_first[name] = 0
                slot_last[name] = 0
        for pos, i in enumerate(comp):
            for out in nx_model.graph.node[i].output:
                s = _resolve_shape(nx_model, u_nx_mapping, out, shape_cache)
                if s is None or len(s) != 4:
                    continue
                aliased = next((v for v in views
                                if v.tensor == out and v.bytes == 0), None)
                if aliased is None:
                    slot_bytes[out] = int(s[1] * s[2] * s[3])
                    slot_first[out] = pos
                    slot_last[out] = pos
        for name in list(slot_bytes):
            consumers = [positions[j] for j, n in
                         enumerate(nx_model.graph.node)
                         if name in n.input and j in positions]
            if consumers:
                slot_last[name] = max([slot_last.get(name, 0)] + consumers)
        # A Slice is a zero-copy view: its consumers extend the backing
        # parent's lifetime.
        for view in views:
            if view.role != 'slice':
                continue
            consumers = [positions[j] for j, n in
                         enumerate(nx_model.graph.node)
                         if view.tensor in n.input and j in positions]
            if consumers and view.backing in slot_last:
                slot_last[view.backing] = max(
                    [slot_last[view.backing]] + consumers)
        # Group slots and their lifetimes.
        for view in views:
            if view.role == 'concat_group':
                slot_bytes[view.tensor] = view.bytes
                input_names = {v.tensor for v in views
                               if v.role == 'concat_slice'
                               and v.backing == view.tensor}
                firsts = [pos for i, pos in positions.items()
                          if any(o in input_names
                                 for o in nx_model.graph.node[i].output)]
                lasts = [pos for i, pos in positions.items()
                         if view.tensor in nx_model.graph.node[i].input]
                slot_first[view.tensor] = min(firsts) if firsts else 0
                slot_last[view.tensor] = (max(lasts) if lasts
                                          else max(positions.values()))
        peak = 0
        for pos in range(len(comp)):
            live = sum(b for name, b in slot_bytes.items()
                       if slot_first.get(name, 0) <= pos <= slot_last.get(name, 0))
            peak = max(peak, live)
        slot_rows = tuple((n, b, slot_first[n], slot_last[n])
                          for n, b in sorted(slot_bytes.items()))
        allocations, alloc_reason = _allocate_slots(
            slot_rows, capacity, entry_names=entries)
        reason = ''
        if peak > capacity:
            reason = f'peak ACTMEM {peak} B exceeds {capacity} B'
        elif alloc_reason:
            reason = alloc_reason
        elif any(v.role == 'slice' and v.channel_offset > 0xFF
                 for v in views):
            reason = 'Slice input channel offset exceeds 8-bit CSR field'
        elif any(v.pixel_stride > 0xFFFF for v in views):
            reason = 'view pixel stride exceeds 16-bit CSR field'
        supported = reason == ''
        regions.append(ResidentRegion(
            tuple(comp), tuple(entries), tuple(exits), tuple(views), peak,
            supported, reason, slot_rows, allocations))
        run.clear(); run_nodes.clear()

    for i in range(starting, until):
        node = nx_model.graph.node[i]
        is_slice_view = False
        if node.op_type == 'Slice' and node.output:
            _, _, nch = _resolve_channel_slice(nx_model, node.output[0])
            is_slice_view = nch is not None
        is_concat_view = (node.op_type == 'Concat' and node.output
                          and concat_views.get(node.output[0]) is not None
                          and concat_views[node.output[0]].supported)
        is_view = is_slice_view or is_concat_view
        if is_nx_node_compilable(node) or is_view:
            run.append(i); run_nodes.add(i)
        elif node.op_type == 'QuantizeLinear' and not run:
            continue
        else:
            close_run()
    close_run()
    return RegionPlan(tuple(regions))


def _build_region_plan(nx_model, u_nx_mapping, concat_views,
                       starting, until, capacity=ACTMEM_BYTES,
                       _depth=0):
    """Build a region plan, recursively splitting oversized DAG candidates.

    The split points are deterministic comp-node boundaries.  A boundary makes
    the left output and right input external tensors; this is conservative but
    legal, and it preserves DAG correctness without trying to solve global
    placement optimally.

    TODO(scheduling): midpoint-proximity is only a deterministic tie-break for
    now.  Once the allocator is in place, rank legal split points
    lexicographically by: both sides feasible; minimum crossing-boundary bytes;
    minimum max(left_peak, right_peak); minimum number of crossing tensors;
    minimum view-group disruption; midpoint/id as the final tie-break.
    """
    plan = _build_region_plan_once(
        nx_model, u_nx_mapping, concat_views, starting, until, capacity)
    if _depth >= 16 or all(r.supported for r in plan.regions):
        return plan

    groups = []
    for view in concat_views.values():
        if not view.supported:
            continue
        members = set()
        for name in view.inputs:
            p = _producer_index(nx_model, name)
            if p is not None:
                members.add(p)
        consumer = next((j for j, n in enumerate(nx_model.graph.node)
                         if view.output in n.input), None)
        if consumer is not None:
            members.add(consumer)
        groups.append(members)

    out = []
    for region in plan.regions:
        if region.supported or len(region.node_ids) <= 1:
            out.append(region)
            continue
        ids = list(region.node_ids)
        id_set = set(ids)
        legal = []
        for pos in range(1, len(ids)):
            mid = ids[pos]
            crosses = any(
                any(n < mid for n in g & id_set)
                and any(n >= mid for n in g & id_set)
                for g in groups)
            if not crosses:
                legal.append(mid)
        if not legal:
            out.append(region)
            continue
        mid = min(legal, key=lambda m: abs(ids.index(m) - len(ids) // 2))
        left = _build_region_plan(
            nx_model, u_nx_mapping, concat_views,
            ids[0], mid, capacity, _depth + 1)
        right = _build_region_plan(
            nx_model, u_nx_mapping, concat_views,
            mid, ids[-1] + 1, capacity, _depth + 1)
        if not left.regions or not right.regions:
            out.append(region)
        else:
            out.extend(left.regions)
            out.extend(right.regions)
    return RegionPlan(tuple(out))


def _build_internal_concat_views(nx_model, u_nx_mapping, starting, until,
                                 capacity=ACTMEM_BYTES):
    """Plan channel-axis Concat groups that can live inside ACTMEM.

    The plan is deliberately conservative: only same-shape, channel-axis
    Concat of compilable producers is supported.  Everything else keeps the
    existing external/L2 fallback behaviour.
    """
    shape_cache = {}

    shape_in_progress = set()

    def shape_for(name):
        """Tensor shape, inferring synthetic split/Concat producer outputs."""
        s = _shape_of_tensor(nx_model, name, shape_cache)
        if s is not None:
            return s
        if name in shape_in_progress:
            return None
        shape_in_progress.add(name)
        try:
            p = _producer_index(nx_model, name)
            if p is None:
                return None
            try:
                mn = u_nx_mapping.get_mapped_node_by_id(p)
            except ValueError:
                # Non-compilable producer: if it is a channel Slice, the
                # output shape is the parent shape with the sliced channels.
                parent, _, nch = _resolve_channel_slice(
                    nx_model, nx_model.graph.node[p].input[0])
                ps = shape_for(parent) if parent != name else None
                if ps is not None and len(ps) == 4:
                    out = ((1, int(nch), ps[2], ps[3]) if nch else ps)
                    shape_cache[name] = out
                    return out
                return None
            parent, _, nch = _resolve_channel_slice(
                nx_model, mn.nx_node.input[0])
            parent_shape = shape_for(parent) if parent != name else None
            if parent_shape is None or len(parent_shape) != 4:
                return None
            in_shape = (1, int(nch) if nch else parent_shape[1],
                        parent_shape[2], parent_shape[3])
            try:
                out = infer_ofmap_shape(
                    ifmap_shape=in_shape,
                    kernel_shape=mn.kernel.shape,
                    pads=mn.pads,
                    stride=mn.strides,
                )
            except Exception:
                return None
            shape_cache[name] = tuple(out)
            return tuple(out)
        finally:
            shape_in_progress.discard(name)

    views = {}
    for idx in range(starting, until):
        node = nx_model.graph.node[idx]
        if node.op_type != 'Concat' or not node.output:
            continue
        axis_attr = next((a for a in node.attribute if a.name == 'axis'), None)
        axis = int(axis_attr.i) if axis_attr is not None else 1
        out_name = node.output[0]
        input_names = tuple(node.input)
        if axis != 1:
            views[out_name] = InternalConcatView(
                out_name, input_names, (), (), 0, 0, 0, (), 0, 0, 0,
                False, f'concat axis {axis} is not channel')
            continue
        shapes = [shape_for(n) for n in input_names]
        if any(s is None or len(s) != 4 for s in shapes):
            views[out_name] = InternalConcatView(
                out_name, input_names, (), (), 0, 0, 0, (), 0, 0, 0,
                False, 'unknown or non-4D concat input shape')
            continue
        hw = {(s[2], s[3]) for s in shapes}
        if len(hw) != 1:
            views[out_name] = InternalConcatView(
                out_name, input_names, (), (), 0, 0, 0, (), 0, 0, 0,
                False, 'concat inputs have different spatial shapes')
            continue
        channels = tuple(int(s[1]) for s in shapes)
        offsets = tuple(int(x) for x in np.cumsum((0,) + channels[:-1]))
        total = int(sum(channels))
        producer_ids = []
        parents = set()
        for n in input_names:
            p = _producer_index(nx_model, n)
            if p is None or not is_nx_node_compilable(nx_model.graph.node[p]):
                producer_ids = []
                break
            producer_ids.append(p)
            parent, _, _ = _resolve_channel_slice(
                nx_model, nx_model.graph.node[p].input[0])
            if parent:
                parents.add(parent)
        if not producer_ids:
            views[out_name] = InternalConcatView(
                out_name, input_names, channels, offsets, total,
                shapes[0][2], shapes[0][3],
                (), 0, 0, 0, False,
                'concat input producer is not compilable')
            continue
        parent_bytes = 0
        for pname in parents:
            ps = shape_for(pname)
            if ps is not None and len(ps) == 4:
                parent_bytes += int(ps[1] * ps[2] * ps[3])
        consumer = next((n for n in nx_model.graph.node
                         if out_name in n.input), None)
        output_bytes = 0
        if consumer is not None and consumer.output:
            os_ = shape_for(consumer.output[0])
            if os_ is not None and len(os_) == 4:
                output_bytes = int(os_[1] * os_[2] * os_[3])
        group_bytes = total * shapes[0][2] * shapes[0][3]
        live_bytes = parent_bytes + group_bytes + output_bytes
        reason = ''
        if total > 0xFFFF:
            reason = 'concat width exceeds 16-bit stride'
        elif max(offsets or (0,)) > 0xFFFF:
            reason = 'concat channel offset exceeds 16 bits'
        elif live_bytes > capacity:
            reason = (f'live ACTMEM {live_bytes} B exceeds {capacity} B')
        views[out_name] = InternalConcatView(
            out_name, input_names, channels, offsets, total,
            shapes[0][2], shapes[0][3], tuple(producer_ids),
            parent_bytes, output_bytes, live_bytes,
            reason == '', reason)
    return views


def traverse_and_compile_nx_graph(
    nx_model     : onnx.ModelProto,
    input_dict   : dict,
    imc_core_size: tuple = (256, 256),
    dwc_core_size: int = 32,
    until        : int = None,
    starting     : int = 0,
    packer = None,
    weight_bits : int | dict = 1,
    real_activations: bool = False,
):
    """Compile a subgraph or the full graph to QRAcc commands.

    .. note::
       This is the **legacy command-emission entry point** retained for
       existing node/chain tests.  Scheduling policy now lives in
       :func:`_build_region_plan`: DAG regions, entries/exits, liveness,
       allocator bases and legal over-budget splits are decided there, and
       this function consumes that plan to emit LOAD/trigger streams.

       The ``starting`` / ``until`` arguments are legacy sub-range selectors;
       they do **not** define a scheduler region.  A region is defined by the
       plan's node set and entry/exit tensors.  New callers that need region
       metadata should build the plan explicitly rather than using these
       bounds as a scheduling API.

       ``weight_bits`` may be a scalar applied to every non-depthwise node or
       a ``{graph_node_id: bits}`` dict.  Depthwise/WSAcc nodes keep their raw
       int8 kernel.  ``real_activations=True`` feeds ONNX-computed
       intermediate tensors instead of random ones; the first compilable node
       writes its ifmap, and subsequent nodes consume the previous node's
       ACTMEM output.
    """
    u_nx_mapping = core.NxModelMapping(
        nx_model,
        imc_core_size=imc_core_size,
        dwc_core_size=dwc_core_size,
        packer = packer
    )

    if until is None:
        until = len(nx_model.graph.node)
    commands = []

    concat_views = _build_internal_concat_views(
        nx_model, u_nx_mapping, starting, until)
    region_plan = _build_region_plan(
        nx_model, u_nx_mapping, concat_views, starting, until)
    region_exits = {tensor for r in region_plan.regions
                    for tensor in r.exits}
    allocation_by_name = {
        a.name: a.base for r in region_plan.regions for a in r.allocations}

    # A Concat group is written with explicit bases only when the whole group
    # is internal.  If any producer (or the group output) is a region exit, the
    # existing compact per-split command form is kept.
    active_views = {}
    for view in concat_views.values():
        if not view.supported:
            continue
        if any(name in region_exits for name in view.inputs):
            continue
        if view.output in region_exits:
            continue
        if view.output not in allocation_by_name:
            continue
        active_views[view.output] = view
    producer_views = {}
    for view in active_views.values():
        for name, off in zip(view.inputs, view.offsets):
            producer_views[name] = (view, off)

    def bits_for(graph_node_id):
        if isinstance(weight_bits, dict):
            return int(weight_bits.get(graph_node_id, 1))
        return int(weight_bits)

    prev_bin_id = None
    current_loaded_ifmap_name = None
    for offset, nx_node in enumerate(nx_model.graph.node[starting:until]):
        graph_node_id = starting + offset
        # Readout is a region-boundary property: an output is read out when it
        # has a consumer outside the resident region or is a graph output.
        readout = any(o in region_exits for o in nx_node.output)
        # The last node in the requested range must be read out even if its
        # ONNX consumers are compilable, otherwise the e2e test has no output.
        if graph_node_id == until - 1:
            readout = True
        next_node = (nx_model.graph.node[graph_node_id + 1]
                     if graph_node_id + 1 < len(nx_model.graph.node) else None)

        if is_nx_node_compilable(nx_node):
            input_tensor = generate_intermediate_tensor(
                nx_model, graph_node_id, input_dict,
                real=real_activations,
            )
            input_parent, slice_offset, slice_channels = _resolve_channel_slice(
                nx_model, nx_node.input[0])
            # A slice consumer reads the parent slot in ACTMEM only when that
            # parent is actually resident.  If the producer was unsupported or
            # evicted, the Slice input is already post-split in external
            # memory and must be loaded compactly.
            input_loaded = input_parent == current_loaded_ifmap_name
            stride = None
            slice_offset_eff = 0
            if slice_channels is not None:
                if input_loaded:
                    parent_view = concat_views.get(input_parent)
                    if parent_view is not None and parent_view.supported:
                        stride = parent_view.total_channels
                    else:
                        parent_id = _producer_index(nx_model, input_parent)
                        if parent_id is not None:
                            stride = int(
                                u_nx_mapping.get_mapped_node_by_id(
                                    parent_id).kernel.shape[0])
                    slice_offset_eff = slice_offset
                else:
                    stride = int(slice_channels)

            # A supported internal Concat is a single logical group: its
            # consumer reads from the group base with the group channel stride.
            input_view = active_views.get(nx_node.input[0])
            ifmap_base = ACTMEM_BASE_NONE
            if input_view is not None:
                input_loaded = True
                stride = input_view.total_channels
                slice_offset_eff = 0
                slice_channels = None
                ifmap_base = allocation_by_name[input_view.output]
            elif input_loaded:
                # Internal parent/slice or normal chained input: use the
                # allocator's base, not the controller's sequential base.
                if slice_channels is not None:
                    ifmap_base = allocation_by_name.get(
                        input_parent, ACTMEM_BASE_NONE)
                else:
                    ifmap_base = allocation_by_name.get(
                        nx_node.input[0], ACTMEM_BASE_NONE)

            # A split that writes into a supported Concat group gets the
            # group's pixel stride, explicit base, and channel offset.
            producer_name = next(
                (o for o in nx_node.output if o in producer_views), None)
            ofmap_stride = None
            ofmap_offset = 0
            ofmap_base = ACTMEM_BASE_NONE
            if producer_name is not None:
                pview, ofmap_offset = producer_views[producer_name]
                ofmap_stride = pview.total_channels
                ofmap_base = allocation_by_name[pview.output]
                if graph_node_id != until - 1:
                    readout = False
            else:
                ofmap_base = allocation_by_name.get(
                    nx_node.output[0], ACTMEM_BASE_NONE)

            next_compilable_id, next_parent = _next_compilable_input(
                nx_model, graph_node_id, until)
            # A non-compilable Slice between two compilable nodes is an
            # internal ACTMEM view, not an external readout point.  Do not
            # trigger a spurious external read just because the immediate
            # consumer is a Slice.
            if (readout and next_compilable_id is not None
                    and next_parent == nx_node.output[0]):
                readout = False

            bits = bits_for(graph_node_id)
            u_code = QrAccNodeCode(
                mapped_node   = u_nx_mapping.get_mapped_node_by_id(graph_node_id),
                mapped_bin    = u_nx_mapping.get_bin_of_node_id(graph_node_id),
                ifmap         = input_tensor,
                imc_core_size = imc_core_size,
                ws_core_size  = dwc_core_size,
                weight_bits   = bits,
                weight_signed = bits > 1,
                nx_model      = nx_model,
                ifmap_channel_stride = stride,
                ifmap_channel_offset = slice_offset_eff,
                ofmap_channel_stride = ofmap_stride,
                ofmap_channel_offset = ofmap_offset,
                ifmap_base = ifmap_base,
                ofmap_base = ofmap_base,
            )

            # preserve_ifmap means "the next node consumes the SAME input",
            # i.e. fan-out.  For a slice consumer, that means the next slice
            # still points at the same parent tensor.  For a normal chain it
            # is never set: the next node must consume this node's output.
            preserve_ifmap = False
            if slice_channels is not None and input_loaded:
                preserve_ifmap = (next_parent == input_parent)
            elif (is_nx_node_compilable(next_node)
                    and next_node.input[0] == u_code.inputs[0]):
                preserve_ifmap = True

            commands += ['INFO']
            commands += [f'{sanitize_name(nx_node.name)}'] # The tb will later parse this as the node name
            commands += [f'Current loaded ifmap: {current_loaded_ifmap_name}']

            print('============ Compiling Node ============')

            if u_code.mapped_node.depthwise:
                print(f"Compiling {nx_node.name} as depthwise node...")
            
            if not input_loaded:
                print(f"Compiling {nx_node.name} as first node of set...")
                commands += [f'NODE {nx_node.name} (id={u_code.mapped_node.node_id}) reading ifmap ({nx_node.input[0]}) from external memory']
            else:
                print(f"Compiling {nx_node.name} as middle node of set...")
                commands += [f'NODE {nx_node.name} (id={u_code.mapped_node.node_id}) will read ifmap ({nx_node.input[0]}) from ACTMEM']

            if readout:
                print(f"{nx_node.name} is followed by a non-compilable node, so it will write the ofmap to external memory.")
                commands += [f'NODE {nx_node.name} (id={u_code.mapped_node.node_id}) will write ofmap ({u_code.outputs[0]}) into external memory']

            if u_code.mapped_node.bin_id is not None:
                if u_code.mapped_node.bin_id != prev_bin_id:
                    print(f"Rewriting bin {nx_node.name} as bin changed from {prev_bin_id} to {u_code.mapped_node.bin_id}...")
                    commands += [f'NODE {nx_node.name} (id={u_code.mapped_node.node_id}) will rewrite the bin from {prev_bin_id} to {u_code.mapped_node.bin_id}']
                else:
                    print(f'NODE {nx_node.name} (id={u_code.mapped_node.node_id}) BIN COMBO!!! Reusing bin {u_code.mapped_node.bin_id}.')
                    commands += [f'This node will reuse the bin {u_code.mapped_node.bin_id} from the previous node']
            else:
                commands += [f'NODE {nx_node.name} (id={u_code.mapped_node.node_id}) is a depthwise node. Loaded bin ({prev_bin_id}) is preserved.']

            if preserve_ifmap:
                commands += [f'NODE {nx_node.name} (id={u_code.mapped_node.node_id}) will preserve the ifmap ({u_code.inputs[0]}) in ACTMEM for the next node.']
                    
            # commands += [u_code.__repr__()]
            commands += ['ENDINFO']
            commands += u_code.compile(
                include_ifmap_writes = not input_loaded,
                # Depthwise/WSAcc weights are not part of the analog bin; load
                # them for every depthwise node even when the bin id is reused.
                write_weights        = (u_code.mapped_node.depthwise
                                        or u_code.mapped_node.bin_id != prev_bin_id),
                add_read             = readout,
                end                  = False ,
                preserve_ifmap       = preserve_ifmap ,
            )

            prev_bin_id = u_code.mapped_node.bin_id if not u_code.mapped_node.depthwise else prev_bin_id  # If the node is depthwise, we don't change the bin id, as it will be the same as the previous node
        
            # In fan-out mode the input remains live; otherwise the node's
            # freshly written output is the activation in ACTMEM.
            if not preserve_ifmap:
                current_loaded_ifmap_name = u_code.outputs[0]

        else:
            print(f'Skipping {nx_node.name} as it is not compilable...')
            # A supported Concat is an internal ACTMEM group.  Its consumer
            # must see the group as the current activation, not as an external
            # tensor.
            if (nx_node.op_type == 'Concat' and nx_node.output
                    and concat_views.get(nx_node.output[0]) is not None
                    and concat_views[nx_node.output[0]].supported):
                current_loaded_ifmap_name = nx_node.output[0]

    commands += ['END'] 
    prev_node = nx_node

    return commands

def get_info_command(u_code):

    """
    Generate an INFO command for the QRAcc testbench.
    This command is used to print information about the node.
    """
    commands = []
    commands += ['INFO']
    commands += [u_code.__repr__()]
    commands += ['ENDINFO']
    return commands

def sanitize_name(name: str) -> str:
    """Return a filesystem-safe version of *name* for use as a filename.

    Strips everything except alphanumerics, hyphens, and underscores,
    then resolves any remaining path tricks via ``pathlib``.
    """
    safe = name.replace(' ', '_')
    safe = ''.join(c for c in safe if c.isalnum() or c in '_-')
    # Use pathlib to collapse any residual traversal components
    safe = pathlib.PurePosixPath(safe).name
    return safe or 'node'
