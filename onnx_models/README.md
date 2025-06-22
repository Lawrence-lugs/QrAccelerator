# ONNX Models used for testing QRAcc

| File Name                                 | Description                                                      |
|--------------------------------------------|------------------------------------------------------------------|
| cifar10_test_bird4.jpg                     | Example CIFAR-10 image (bird class) used for model testing.      |
| mbv2_cifar10_int8_split_binarized.onnx     | Quantized MobileNetV2 ONNX model for CIFAR-10, split regular/PwC into K=256 C=256 chunks, DwC split into C=K=32 chunks, and regular/PwC are initialized to random binary. |
| mbv2_cifar10_int8.onnx                     | Quantized MobileNetV2 ONNX model for CIFAR-10 (int8).            |
| README.md                                  | Documentation for the ONNX models in this directory.             |