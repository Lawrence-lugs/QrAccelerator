"""Pytest configuration and fixtures for QrAccelerator RTL and model tests.

Defines CLI options (--simulator, --seed, --mode, etc.), parametrization
logic, and shared fixtures for ONNX model loading and image preprocessing.
"""

from PIL import Image
import shutil
import pytest
import numpy as np
try:
    import onnx
except ImportError:
    onnx = None

valid_simulators = ['xrun', 'vcs', 'verilator']

def _detect_default_simulator():
    """Auto-detect an available HDL simulator, preferring VCS > Xcelium > Verilator."""
    for sim in ['vcs', 'xrun', 'verilator']:
        if shutil.which(sim):
            return sim
    return None

def pytest_addoption(parser):
    parser.addoption(
        "--simulator",
        action="append",
        default=[],
        help="simulator to test with",
    )
    parser.addoption(
        "--col_symmetric",
        action="store_true",
        default=False,
        help="all columns are tested the same",
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
        "--figures",
        action="store_true",
        default=False,
        help="enable figure generation (PNGs in images/png/)",
    )
    parser.addoption(
        "--heavy",
        action="store_true",
        default=False,
        help="run long full-model simulations",
    )
    parser.addoption(
        "--proprietary",
        action="store_true",
        default=False,
        help="run tests needing Cadence/Synopsys tools or synthesized netlists",
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
            metafunc.parametrize("simulator", [_detect_default_simulator()])
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

    if 'weight_mode' in metafunc.fixturenames:
        metafunc.parametrize("weight_mode", ['bipolar','binary'])

    if "modelpath" in metafunc.fixturenames:
        if metafunc.config.getoption("modelpath") == []:
            metafunc.parametrize("modelpath", ['onnx_models/mbv2_cifar10_int8.onnx'])
        else:
            metafunc.parametrize("modelpath", metafunc.config.getoption("modelpath"))

def pytest_collection_modifyitems(config, items):
    heavy = config.getoption("--heavy")
    proprietary = config.getoption("--proprietary")
    verilator_available = shutil.which('verilator') is not None
    for item in items:
        # proprietary marker
        if item.get_closest_marker("proprietary") and not proprietary:
            item.add_marker(pytest.mark.skip(reason="proprietary test: needs Cadence/Synopsys tools or synthesized netlists; run with --proprietary"))
        # ams marker: needs analog co-simulation outputs that are not in the repo
        if item.get_closest_marker("ams") and not proprietary:
            item.add_marker(pytest.mark.skip(reason="ams test: needs AMS co-simulation outputs in tb/*/inputs (not in repo); run with --proprietary"))
        # heavy marker
        if item.get_closest_marker("heavy") and not heavy:
            item.add_marker(pytest.mark.skip(reason="heavy test: long full-model simulations; run with --heavy"))
        # needs_verilator marker
        if item.get_closest_marker("needs_verilator") and not verilator_available:
            item.add_marker(pytest.mark.skip(reason="verilator not found on PATH (install verilator or run inside the devcontainer)"))
        # simulator parameter: skip only for tests parametrized by `simulator`
        simulator_params = item.callspec.params if hasattr(item, 'callspec') else {}
        if 'simulator' in simulator_params:
            simulator = simulator_params['simulator']
            if simulator is None:
                item.add_marker(pytest.mark.skip(reason="no HDL simulator (verilator/vcs/xrun) found on PATH"))
            elif simulator in ('xrun', 'vcs') and shutil.which(simulator) is None:
                item.add_marker(pytest.mark.skip(reason=f"{simulator} not found on PATH (install {simulator} or run inside the devcontainer)"))

def _normalize_cifar(path):
    img = np.asarray(Image.open(path).convert('RGB'), dtype=np.float32) / 255.0
    mean = np.array((0.4914, 0.4822, 0.4465), dtype=np.float32)
    std = np.array((0.2023, 0.1994, 0.2010), dtype=np.float32)
    img = (img - mean) / std
    return img.transpose(2, 0, 1)[np.newaxis]

@pytest.fixture
def img_array():    
    return _normalize_cifar('onnx_models/cifar10_test_bird4.jpg')

@pytest.fixture
def nx_model(modelpath):
    nx_model = onnx.load(modelpath)
    return nx_model

@pytest.fixture
def nx_input_dict(nx_model, img_array):
    input_name = nx_model.graph.input[0].name
    input_dict = {input_name: img_array}
    return input_dict

@pytest.fixture
def figures(request):
    return request.config.getoption("--figures")