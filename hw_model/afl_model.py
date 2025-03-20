import numpy as np
import pandas as pd
df = pd.DataFrame
import hwacctools.comp_graph.compute as compute

def roll_arithmetic_2d(a, shift : tuple[int]):
    '''
    Shifts 2d array a by shift
    '''
    if shift[0] > 0:
        a = np.roll(a, shift[0], axis=0)
        a[:shift[0]] = 0
    elif shift[0] < 0:
        a = np.roll(a, shift[0], axis=0)
        a[shift[0]:] = 0
    if shift[1] > 0:
        a = np.roll(a, shift[1], axis=1)
        a[:,:shift[1]] = 0
    elif shift[1] < 0:
        a = np.roll(a, shift[1], axis=1)
        a[:,shift[1]:] = 0
    return a

def generate_shift_control_matrices_fx_window(nchannels, depth,ksize=3):
    '''
    Shifting with shift matrices for toeplitz
    0 - no shift 
    1 - vertical shift
    2 - horizontal shift 
    3 - diagonal shift
    '''
    shift_matrices = []
    shift_matrix = np.zeros((depth,nchannels*ksize), dtype=np.int32)
    shift_matrix[0][:8] = 2
    shift_matrices.append(np.copy(shift_matrix)) # apparently this thing passes reference otherwise
    shift_matrix[0][:] = 0
    for i in range(0, depth+1):
        shift_matrix = roll_arithmetic_2d(shift_matrix, (1, 0))
        shift_matrix[0][ (3*i) :] = 3
        recipient_matrix = roll_arithmetic_2d(shift_matrix, (1, 0))
        offset = 3*(i+1)
        recipient_matrix[0][offset:offset+8] = 2
        shift_matrices.append(recipient_matrix)
    return np.array(shift_matrices)

def generate_shift_control_matrices_windowed(nchannels, depth, ksize=3):
    '''
    Shifting with shift matrices for toeplitz
    0 - no shift 
    1 - vertical shift
    2 - horizontal shift 
    3 - diagonal shift
    '''
    shift_matrices = []
    shift_matrix = np.zeros((depth,nchannels*ksize*ksize), dtype=np.int32)
    window_matrices = generate_shift_control_matrices_fx_window(nchannels,depth,ksize)

    for t in range(depth+1):
        for i in range(ksize):
            shift_matrix[:,i*nchannels*ksize:(i+1)*nchannels*ksize] = window_matrices[t]
        shift_matrices.append(np.copy(shift_matrix))
    
    return np.array(shift_matrices)

def generate_shift_control_matrices(shape : tuple[int],ksize=3):
    '''
    Shifting with shift matrices for toeplitz
    0 - no shift 
    1 - vertical shift
    2 - horizontal shift 
    3 - diagonal shift
    '''
    shift_matrices = []
    shift_matrix = np.zeros(shape, dtype=np.int32)
    shift_matrix[0][:8] = 2
    shift_matrices.append(np.copy(shift_matrix)) # apparently this thing passes reference otherwise
    shift_matrix[0][:] = 0
    for i in range(0, 7):
        shift_matrix = roll_arithmetic_2d(shift_matrix, (1, 0))
        shift_matrix[0][ (1 + 3*i) :] = 3
        # The shift command is given to the recipient, not the sender.
        recipient_matrix = roll_arithmetic_2d(shift_matrix, (1, -1))
        offset = 3*(i+1)
        recipient_matrix[0][offset:offset+8] = 2
        shift_matrices.append(recipient_matrix)
    return np.array(shift_matrices)

class Afl():
    def __init__(self, dimX, dimY):
        self.dimX = dimX
        self.dimY = dimY
        self.afl = np.zeros((dimX, dimY), dtype=np.int32) - 1

    def load_input(self, in_vec, offset):
        wr_vec = np.zeros(self.dimY, dtype=np.int32) - 1
        if len(in_vec) < self.dimY:
            wr_vec[offset:len(in_vec)+offset] = in_vec
        self.afl[0] = wr_vec
        return self
    
    def load_shifted(self,in_col, out_col, offset):
        if offset > 0:
            self.afl[out_col][offset:] = self.afl[in_col][:-offset]
        else:
            self.afl[out_col][-offset:] = self.afl[in_col][-offset:]
        return self
    
    def shift_all(self, shift_matrix, shift_in):
        '''
        Shifts according to shift matrix
        '''
        overall = np.vstack((shift_in, self.afl))
        for x in range(self.dimX):
            for y in range(self.dimY):
                if shift_matrix[x][y] == 3:
                    self.afl[x][y] = overall[x][y+1]
                elif shift_matrix[x][y] == 2:
                    self.afl[x][y] = overall[x][y]
                elif shift_matrix[x][y] == 1:
                    self.afl[x][y] = overall[x+1][y+1]

if __name__ == '__main__':

    pd.set_option('display.max_rows', 500)
    pd.set_option('display.max_columns', 500)
    pd.set_option('display.width', 1000)

    # 10x10 image
    acts = np.array([
        [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
        [11, 12, 13, 14, 15, 16, 17, 18, 19, 20],
        [21, 22, 23, 24, 25, 26, 27, 28, 29, 30],
        [31, 32, 33, 34, 35, 36, 37, 38, 39, 40],
        [41, 42, 43, 44, 45, 46, 47, 48, 49, 50],
        [51, 52, 53, 54, 55, 56, 57, 58, 59, 60],
        [61, 62, 63, 64, 65, 66, 67, 68, 69, 70],
        [71, 72, 73, 74, 75, 76, 77, 78, 79, 80],
        [81, 82, 83, 84, 85, 86, 87, 88, 89, 90],
        [91, 92, 93, 94, 95, 96, 97, 98, 99, 100]
    ]).reshape(1,10,10).repeat(3,axis=0)
    acts[1] = acts[1]*10
    acts[2] = acts[2]*100
    acts.shape
    sample_tplitz = compute.toeplitzize_input(acts, 3, 1)

    # acts = acts.transpose(1,2,0) # C H W -> H W C
    acts_reference = acts
    # acts_reference = np.pad(acts, ((0,0),(1,1),(1,1)), mode='constant')
    acts_memory = acts_reference.copy().flatten()

    # Striding locations
    c_stride = acts_reference.shape[2] * acts_reference.shape[1]
    fy_stride = acts_reference.shape[1]

    aflDimX = 6
    aflDimY = 27
    u_afl = Afl(aflDimX, aflDimY)

    # Shifting with shift matrices for toeplitz
    control_matrices = generate_shift_control_matrices(u_afl.afl.shape)

    for c in range(len(control_matrices)):
        shift_in = np.zeros(u_afl.dimY, dtype=np.int32) - 1
        if c < acts.shape[0]:
            addr = c * c_stride
            shift_in[:8] = acts_memory[addr:addr+8]
            shift_in = np.roll(shift_in, 3*c, axis=0)
        u_afl.shift_all(control_matrices[c], shift_in)
        print(df(u_afl.afl))