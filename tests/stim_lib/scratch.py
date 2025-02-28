#%%

import numpy as np

a = np.random.rand(3,224,224)

# %%

c = 2 # Slowest Changing Dim
iy = 129
ix = 155 # Fastest Changing Dim

# How much you add to direction based on C index
stride_c = a.shape[1] * a.shape[2]
# How much you add to direction based on Y index
stride_iy = a.shape[2]

print(a[c,iy,ix])
print(a.flatten()[c*stride_c + iy*stride_iy + ix])