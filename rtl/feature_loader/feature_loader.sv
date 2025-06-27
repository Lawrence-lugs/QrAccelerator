// Element-addressable feature loader
// Actually just a regfile
`timescale 1ns/1ps

import qracc_pkg::*;

module feature_loader #(
    parameter inputWidth    = 256   ,
    parameter addrWidth     = 8     , 
    parameter elementWidth  = 8     ,
    parameter numElements   = 128   
) (
    input clk, nrst,

    input logic [inputWidth-1:0]    data_i  ,
    input logic [addrWidth-1:0]     addr_i  ,
    input logic wr_en,

    output logic [numElements-1:0][elementWidth-1:0] data_o,

    input logic [9:0] mask_start,
    input logic [9:0] mask_end
);

logic [elementWidth-1:0] staging_register [numElements];

always_ff @( posedge clk or negedge nrst ) begin : writeDecode
    if (!nrst) begin
        for (int i = 0; i < numElements; i++) begin
            staging_register[i] <= 0;
        end
    end else begin
        if (wr_en) begin            
            `ifdef TRACK_STATISTICS
            stats.statFLWrites++;
            `endif
            for (int i = 0; i < inputWidth/elementWidth; i++) begin
                staging_register[addr_i + i] <= data_i[(inputWidth/elementWidth-1-i)*elementWidth +: elementWidth];
            end
        end
    end
end

always_comb begin : outDecode
    for (int i = 0; i < numElements; i++) begin
        if (i >= mask_start && i < mask_end) begin
            data_o[i] = staging_register[i];
        end else begin
            data_o[i] = 0;
        end
    end
end

endmodule