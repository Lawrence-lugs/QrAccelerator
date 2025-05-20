
// This module aligns offsetted mmul outputs to the leftmost
// 

`timescale 1ns/1ps

import qracc_pkg::*;

module mm_output_aligner #(
    parameter numColsPerBank = 32,
    parameter elementBits = 8,
    parameter numElements = 256
) (
    input clk, nrst,

    input valid_i,
    input [numElements-1:0][elementBits-1:0] data_i,
    input qracc_config_t cfg_i,

    output [numElements-1:0][elementBits-1:0] data_o
);


    
endmodule