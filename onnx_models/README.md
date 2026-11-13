# ONNX Models used for testing QRAcc

| File Name                                 | Description                                                      |
|--------------------------------------------|------------------------------------------------------------------|
| `cifar10_test_bird4.jpg`                   | Example CIFAR-10 image (bird class) used for model testing.     |
| `mbv2_cifar10_int8.onnx`                   | Quantized MobileNetV2 ONNX model for CIFAR-10 (int8).           |
| `mbv2_cifar10_int8_binary.onnx`            | Binary variant of the MobileNetV2 int8 model; variant used by `tests/test_marp*.py`. |
| `mbv2_cifar10_int8_binary_split.onnx`      | Split binary variant; variant used by `tests/test_marp*.py`.     |
| `mbv2_cifar10_int8_split_binarized.onnx`   | Split binarized variant.                                         |

The terms "binary" and "split" are described only as far as the code shows
(grep `binary` / `split` in `tests/test_marp*.py` and MARP usage). Where the
code does not disambiguate, each file is a variant used by
`tests/test_marp*.py` and is marked here for user review.

These models are loaded by `tests/test_marp.py` and `tests/test_marp_rtl.py`.
Loading happens inside test bodies (guarded by `pytest.skip` when a path is
missing, i.e. when the `third_party/MARP` submodule has not been initialized
with `git submodule update --init --recursive`).
