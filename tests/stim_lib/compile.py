import numpy as np
from .stimulus_gen import *

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