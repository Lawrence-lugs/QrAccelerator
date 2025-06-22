import numpy as np
from .stimulus_gen import *
from hwacctools.comp_graph import compute, cgraph, cnodes, core

def make_trigger_write(
    command,
    clear=0,
    inst_write_mode=0,
    csr_main_trigger_enum=None,
    write_address='00000010'  # Default CSR base address for MAIN
):
    """
    command: string, one of:
        'TRIGGER_IDLE', 'TRIGGER_LOAD_ACTIVATION', 'TRIGGER_LOADWEIGHTS_PERIPHS',
        'TRIGGER_COMPUTE_ANALOG', 'TRIGGER_COMPUTE_DIGITAL', 'TRIGGER_READ_ACTIVATION'
    clear: 0 or 1, sets the clear bit
    inst_write_mode: 0 or 1, sets the inst_write_mode bit
    csr_main_trigger_enum: optional dict mapping string to value, otherwise uses default mapping
    write_address: hex string, address to write to (default 0x10)
    """
    # Default mapping from qracc_pkg.svh
    if csr_main_trigger_enum is None:
        csr_main_trigger_enum = {
            'TRIGGER_IDLE': 0,
            'TRIGGER_LOAD_ACTIVATION': 1,
            'TRIGGER_LOADWEIGHTS_PERIPHS': 2,
            'TRIGGER_COMPUTE_ANALOG': 3,
            'TRIGGER_COMPUTE_DIGITAL': 4,
            'TRIGGER_READ_ACTIVATION': 5,
            'TRIGGER_LOADWEIGHTS_PERIPHS_DIGITAL': 6
        }
    if command not in csr_main_trigger_enum:
        raise ValueError(f"Unknown command: {command}")

    trigger_val = csr_main_trigger_enum[command] & 0x7
    clear_val = (clear & 0x1) << 3
    inst_write_mode_val = (inst_write_mode & 0x1) << 5

    word = trigger_val | clear_val | inst_write_mode_val
    return [f'LOAD {write_address} {word:08x}']

def bundle_config_into_write(
    config_dict,
    config_write_address = '00000010' # in hex, base address for CSR
):
    # CSR register addresses (offsets from base)
    CSR_REG_CONFIG      = 1
    CSR_REG_IFMAP_DIMS  = 2
    CSR_REG_OFMAP_DIMS  = 3
    CSR_REG_CHANNELS    = 4
    CSR_REG_OFFSETS     = 5
    CSR_REG_PADDING     = 6

    base_addr = int(config_write_address, 16)

    # Pack fields into 32-bit words
    config_word = (
        ((config_dict['n_output_bits_cfg']      & 0xF) << 28) |
        ((config_dict['n_input_bits_cfg']       & 0xF) << 24) |
        ((config_dict['stride_y']               & 0xF) << 20) |
        ((config_dict['stride_x']               & 0xF) << 16) |
        ((config_dict['filter_size_x']          & 0xF) << 12) |
        ((config_dict['filter_size_y']          & 0xF) << 8)  |
        ((config_dict['adc_ref_range_shifts']   & 0xF) << 4)  |
        ((config_dict['unsigned_acts']          & 0x1) << 1)  |
        ((config_dict['binary_cfg']             & 0x1) << 0)
    )
    ifmap_dims_word = (
        ((config_dict['input_fmap_dimy'] & 0xFFFF) << 16) |
        ((config_dict['input_fmap_dimx'] & 0xFFFF) << 0)
    )
    ofmap_dims_word = (
        ((config_dict['output_fmap_dimy'] & 0xFFFF) << 16) |
        ((config_dict['output_fmap_dimx'] & 0xFFFF) << 0)
    )
    channels_word = (
        ((config_dict['num_output_channels'] & 0xFFFF) << 16) |
        ((config_dict['num_input_channels']  & 0xFFFF) << 0)
    )
    offsets_word = (
        ((config_dict['mapped_matrix_offset_y'] & 0xFFFF) << 16) |
        ((config_dict['mapped_matrix_offset_x'] & 0xFFFF) << 0)
    )
    padding_word = (
        ((config_dict['padding_value'] & 0xFFFF) << 4) |
        ((config_dict['padding'] & 0xFFFF) << 0)
    )

    # List of (address, hex_word) for each CSR
    config_writes = [
        f"LOAD {base_addr + CSR_REG_CONFIG:08x} {config_word:08x}",
        f"LOAD {base_addr + CSR_REG_IFMAP_DIMS:08x} {ifmap_dims_word:08x}",
        f"LOAD {base_addr + CSR_REG_OFMAP_DIMS:08x} {ofmap_dims_word:08x}",
        f"LOAD {base_addr + CSR_REG_CHANNELS:08x} {channels_word:08x}",
        f"LOAD {base_addr + CSR_REG_OFFSETS:08x} {offsets_word:08x}",
        f"LOAD {base_addr + CSR_REG_PADDING:08x} {padding_word:08x}"  # Assuming padding is at CSR_REG_PADDING
    ]
    
    return config_writes

def write_array_to_asm(write_array, address='00000100'):
    asm = []
    for element in write_array:
        asm.append(f"LOAD {address} {vhex3(element)}")
    return asm

def get_config_from_mapped_node(
    mapped_node : core.MappedOnnxNode,
    ifmap_shape : tuple,
    ifmap_bits = 8,
    ofmap_bits = 8
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
        weights=mapped_node.matrix.T,
        ifmap_bits=ifmap_bits
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
        "mapped_matrix_offset_x": mapped_node.offset_x,
        "mapped_matrix_offset_y": mapped_node.offset_y,
        "padding": mapped_node.pads[0],  # Use 0 padding for soft padding
        "padding_value": mapped_node.x_zp,  # Padding value for the input feature map
    }

    return config_dict