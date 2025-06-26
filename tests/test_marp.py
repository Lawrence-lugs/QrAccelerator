import numpy as np
from tests.stim_lib.stimulus_gen import *
from tests.stim_lib.compile import *
from hwacctools.comp_graph import compute, cgraph, cnodes, core
from hwacctools.onnx_tools import onnx_splitter
import hwacctools.onnx_utils as onnx_utils
import hwacctools.quantization.quant as quant
import pytest

def test_create_nx_mapping():

    nx_model = onnx.load('onnx_models/mbv2_cifar10_int8_binary.onnx')

    imc_core_size = (256,256)
    dwc_core_size = 32
    mnode_index = 2

    u_nx_mapping = core.NxModelMapping(
        nx_model,
        imc_core_size=imc_core_size,
        dwc_core_size=dwc_core_size
    )

@pytest.mark.parametrize(
    "depthwise, kernel_shape, ifmap_shape, mm_offset_x, mm_offset_y, core_shape, padding, stride",
    [
        (False, (32, 3, 3, 3), (1, 3, 32, 32), 0, 0, (256, 256), 1, 1),
        (True, (32, 1, 3, 3), (1, 32, 32, 32), 0, 0, (256, 256), 1, 1),
        (False, (64, 3, 3, 3), (1, 3, 64, 64), 120, 90, (256, 256), 1, 2),
    ],
)
def test_produce_single_node_test(
    depthwise,
    kernel_shape,
    ifmap_shape,
    mm_offset_x,
    mm_offset_y,
    core_shape,
    padding,
    stride,
):

    u_code = QrAccNodeCode.produce_single_node_test(
        ifmap_shape = ifmap_shape,
        kernel_shape = kernel_shape,
        offset_x = mm_offset_x,
        offset_y = mm_offset_y,
        core_size = core_shape,
        ws_core_size = 32,
        pads = (padding, padding, padding, padding),
        stride = (stride, stride),
        depthwise = depthwise,
    )
    u_code.compile()

def test_marp_compilation_all_nodes_in_onnx(
    modelpath = 'onnx_models/mbv2_cifar10_int8_binary.onnx',
    imc_core_size = (256, 256),
    dwc_core_size = 32
):    
    # Running a single node from a model
    nx_model = onnx.load(modelpath)

    u_nx_mapping = core.NxModelMapping(
        nx_model,
        imc_core_size=imc_core_size,
        dwc_core_size=dwc_core_size
    )

    input_dict = {
        'input.1': np.random.rand(1, 3, 32, 32).astype(np.float32)
    }

    commands = []
    for mnode_index in range(len(u_nx_mapping.mapped_nodes)):
        node = u_nx_mapping.mapped_nodes[mnode_index]
        node_id = node.node_id
        bin = u_nx_mapping.mapped_bins[node.bin_id] if not node.depthwise else None

        input_tensor_shape = onnx_utils.get_intermediate_tensor_value(
            nx_model, nx_model.graph.node[node_id].input[0], input_dict=input_dict).shape
        input_tensor = np.random.randint(0, 256, input_tensor_shape).astype(np.uint8)

        u_code = QrAccNodeCode(
            mapped_node = node,
            mapped_bin = bin,
            ifmap = input_tensor,
            imc_core_size = imc_core_size,
            ws_core_size = dwc_core_size,
            nx_model = nx_model
        )

        if mnode_index == 0: 
            # First node, include ifmap writes but do not read
            commands += u_code.compile(include_ifmap_writes=True,add_read=False)
        elif mnode_index == len(u_nx_mapping.mapped_nodes) - 1:  
            # Last node, include read
            commands += u_code.compile(include_ifmap_writes=False, add_read=True)
        else:
            commands += u_code.compile(include_ifmap_writes=False, add_read=False)

def test_marp_run_entire_mbv2(
    nx_model = onnx.load('onnx_models/mbv2_cifar10_int8_binary.onnx'),
    imc_core_size = (256,256),
    dwc_core_size = 32
):

    u_nx_mapping = core.NxModelMapping(
        nx_model,
        imc_core_size=imc_core_size,
        dwc_core_size=dwc_core_size
    )

    input_dict = {
        'input.1': np.random.rand(1, 3, 32, 32).astype(np.float32)
    }

    prev_node = None
    next_node = None
    prev_bin_id = None
    for node_id,nx_node in enumerate(nx_model.graph.node):
        
        next_node = nx_model.graph.node[node_id + 1] if node_id + 1 < len(nx_model.graph.node) else None

        if is_nx_node_compilable(nx_node):
            input_tensor = generate_random_intermediate_tensor(
                nx_model, node_id, input_dict
            )
            u_code = QrAccNodeCode(
                mapped_node = u_nx_mapping.get_mapped_node_by_id(node_id),
                mapped_bin = u_nx_mapping.get_bin_of_node_id(node_id),
                ifmap = input_tensor,
                imc_core_size = imc_core_size,
                ws_core_size = dwc_core_size,
                nx_model = nx_model
            )

            print('============ Compiling Node ============')
            if u_code.mapped_node.depthwise:
                print(f"Compiling {nx_node.name} as depthwise node...")
            else:
                if not is_nx_node_compilable(prev_node):
                    print(f"Compiling {nx_node.name} as first node of set...")
                elif not is_nx_node_compilable(next_node):
                    print(f"Compiling {nx_node.name} as last node of set...")
                if u_code.mapped_node.bin_id != prev_bin_id:
                    print(f"Rewriting bin {nx_node.name} as bin changed from {prev_bin_id} to {u_code.mapped_node.bin_id}...")
                else:
                    print(f'Reusing bin {u_code.mapped_node.bin_id} for {nx_node.name}...')

            u_code.compile(
                include_ifmap_writes=not is_nx_node_compilable(prev_node),  # If the previous node was not compilable, we need to write the input feature map 
                write_weights = u_code.mapped_node.bin_id != prev_bin_id,    # We only write weights if the bin has changed
                add_read = not is_nx_node_compilable(next_node),            # We don't need to readout if the next node can be run by the accelerator
            )
            prev_bin_id = u_code.mapped_node.bin_id if not u_code.mapped_node.depthwise else prev_bin_id  # If the node is depthwise, we don't change the bin id, as it will be the same as the previous node
        else:
            print(f'Skipping {nx_node.name} as it is not compilable...')

        prev_node = nx_node
