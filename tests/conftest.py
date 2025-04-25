from torchvision import transforms
from PIL import Image
import pytest
import numpy as np
import onnx

valid_simulators = ['xrun','vcs']

def pytest_addoption(parser):
    parser.addoption(
        "--simulator",
        action="append",
        default=[],
        help="simulator to test with",
    )
    parser.addoption(
        "--synth",
        action="append",
        default=False,
        help="performs synthesis during tests",
    )
    parser.addoption(
        "--col_symmetric",
        action="store_true",
        default=False,
        help="all columns are tested the same",
    )
    parser.addoption(
        "--postsynth",
        action="store_true",
        default=False,
        help="performs post-synthesis simulation during tests",
    )
    parser.addoption(
        "--seed",
        action="append",
        default=[0],
        help="seed for random number generator",
    )
    parser.addoption(
        "--mode",
        action="append",
        default=['random'],
        help="values to test. options: max, min, random, all",
    )
    parser.addoption(
        "--modelpath",
        action="append",
        default=[],
        help="onnx model file path",
    )
    parser.addoption(
        "--core_size",
        action="append",
        default=[(256,256)],
        help="core size for accelerator",
    )

def pytest_generate_tests(metafunc):
    if "simulator" in metafunc.fixturenames:
        # Check if simulator is in supported
        for simulator in metafunc.config.getoption("simulator"):
            if simulator not in valid_simulators:
                raise ValueError(
                    f'Invalid simulator: {metafunc.config.getoption("simulator")}. Valid simulators: {valid_simulators}'
                )
        if metafunc.config.getoption("simulator") == []:
            metafunc.parametrize("simulator", ['vcs'])
        else:
            metafunc.parametrize("simulator", metafunc.config.getoption("simulator"))

    if 'col_symmetric' in metafunc.fixturenames:
        metafunc.parametrize("col_symmetric", [metafunc.config.getoption("col_symmetric")])

    if 'mode' in metafunc.fixturenames:
        if 'all' in metafunc.config.getoption("mode"):
            metafunc.parametrize("mode", ['random','max','min'])
        else:
            metafunc.parametrize("mode", metafunc.config.getoption("mode"))

    if 'seed' in metafunc.fixturenames:
        metafunc.parametrize("seed", metafunc.config.getoption("seed"))

    if 'synth' in metafunc.fixturenames:
        metafunc.parametrize("synth", metafunc.config.getoption("synth"))

    if 'weight_mode' in metafunc.fixturenames:
        metafunc.parametrize("weight_mode", ['bipolar','binary'])

    if "modelpath" in metafunc.fixturenames:
        if metafunc.config.getoption("modelpath") == []:
            metafunc.parametrize("modelpath", ['hwacc_design_garage/onnx_models/mbv2_cifar10_int8.onnx'])
        else:
            metafunc.parametrize("modelpath", metafunc.config.getoption("modelpath"))

    if "core_size" in metafunc.fixturenames:
        metafunc.parametrize("core_size", metafunc.config.getoption("core_size"))

t_normalize = transforms.Compose([
    transforms.ToTensor(),
    transforms.Normalize((0.4914, 0.4822, 0.4465), (0.2023, 0.1994, 0.2010)),
])

@pytest.fixture
def img_array():    
    img = Image.open('hwacc_design_garage/images/cifar10_test_bird4.jpg')
    img_array = t_normalize(img).unsqueeze(0).numpy()
    return img_array

@pytest.fixture
def nx_model(modelpath):
    nx_model = onnx.load(modelpath)
    return nx_model

@pytest.fixture
def nx_input_dict(nx_model, img_array):
    input_name = nx_model.graph.input[0].name
    input_dict = {input_name: img_array}
    return input_dict