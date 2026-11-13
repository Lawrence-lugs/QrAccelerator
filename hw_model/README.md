# hw_model

Behavioral (pure-Python) hardware models for the QR accelerator.

## afl_model.py

`hw_model/afl_model.py` is a behavioral model of the Aligned Feature Loader
(AFL): it shifts and loads activation data into a 2-D register file so that
Toeplitz-formatted inputs can be fed column-by-column to the QR accelerator
array. It is a pure-Python reference used by higher-level tests.

`afl_model.py` imports MARP (`marp.compile.compute`), so it requires the
`third_party/MARP` submodule to be initialized and installed
(`git submodule update --init --recursive` + `pip install -e ./third_party/MARP`).

It is not used by the `tests/` pytest suite directly.
