
// This module aligns offsetted mmul outputs to the leftmost
// 

`timescale 1ns/1ps

import qracc_pkg::*;

module mm_output_aligner #(
    parameter numColsPerBank = 32,
    parameter elementBits = 8,
    parameter numElements = 256
) (
    input [numElements-1:0][elementBits-1:0] data_i,
    input qracc_config_t cfg_i,
    output logic [numElements-1:0][elementBits-1:0] data_o
);

always_comb begin
    for(int i = 0; i < numElements; i++) begin
        if( i + cfg_i.mapped_matrix_offset_x >= numElements ) begin
            data_o[i] = '0;
        end else begin
            data_o[i] = data_i[i + cfg_i.mapped_matrix_offset_x];
        end
    end
end
    
endmodule