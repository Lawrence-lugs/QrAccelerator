// Element-addressable feature loader
`timescale 1ns/1ps

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

    output logic [numElements-1:0][elementWidth-1:0] data_o
);

logic [elementWidth-1:0] staging_register [numElements];

always_ff @( posedge clk or negedge nrst ) begin : writeDecode
    if (!nrst) begin
        for (int i = 0; i < numElements; i++) begin
            staging_register[i] <= 0;
        end
    end else begin
        if (wr_en) begin
            staging_register[addr_i] <= data_i;
        end
    end
end

always_comb begin : outDecode
    for (int i = 0; i < numElements; i++) begin
        data_o[i] <= staging_register[i];
    end
end

endmodule