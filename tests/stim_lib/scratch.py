# %%

import hwacctools as cgraph
import onnx
from onnx import numpy_helper as nphelp
import numpy as np
from torchvision import models, transforms

nx_model = onnx.load('')