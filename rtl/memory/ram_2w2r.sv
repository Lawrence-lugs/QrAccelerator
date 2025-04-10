// 4 port RAM
// Single cycle response
// Little Endian

`timescale 1ns/1ps

module ram_2w2r #(
    parameter addrWidth = 32,
    parameter dataSize = 8,

    parameter interfaceWidth1 = 32,
    parameter interfaceWidth2 = 256,
    
    parameter depth = 1024
) (
    input logic clk, nrst,

    input logic wr_en_1_i,
    input logic [addrWidth-1:0] wr_addr_1_i,
    input logic [interfaceWidth1-1:0] wr_data_1_i,
    input logic rd_en_1_i,
    input logic [addrWidth-1:0] rd_addr_1_i,
    output logic [interfaceWidth1-1:0] rd_data_1_o,

    input logic wr_en_2_i,
    input logic [addrWidth-1:0] wr_addr_2_i,
    input logic [interfaceWidth2-1:0] wr_data_2_i,
    input logic rd_en_2_i,
    input logic [addrWidth-1:0] rd_addr_2_i,
    output logic [interfaceWidth2-1:0] rd_data_2_o
);

logic [dataSize-1:0] mem [depth];

localparam nDataInInterface1 = interfaceWidth1/dataSize;
localparam nDataInInterface2 = interfaceWidth2/dataSize;

always_ff @(posedge clk, negedge nrst) begin
    if (!nrst) begin
        for (int i = 0; i < depth; i++) begin
            // mem[i] <= 0; // Comment when we want to see exactly which parts are written
        end
        rd_data_1_o <= 0;
        rd_data_2_o <= 0;
    end else begin
        if (wr_en_1_i) begin
            for (int i = 0; i < interfaceWidth1/dataSize; i++) begin
                mem[wr_addr_1_i + i] <= wr_data_1_i[(interfaceWidth1/dataSize-1-i)*dataSize +: dataSize];
            end
        end
        if (wr_en_2_i) begin
            for (int i = 0; i < interfaceWidth2/dataSize; i++) begin
                mem[wr_addr_2_i + i] <= wr_data_2_i[(interfaceWidth2/dataSize-1-i)*dataSize +: dataSize];
            end
        end
        if (rd_en_1_i) begin
            for (int i = 0; i < interfaceWidth1/dataSize; i++) begin
                rd_data_1_o[i*dataSize +: dataSize] <= mem[rd_addr_1_i + (interfaceWidth1/dataSize-1-i)];
            end
        end
        if (rd_en_2_i) begin
            for (int i = 0; i < interfaceWidth2/dataSize; i++) begin
                rd_data_2_o[i*dataSize +: dataSize] <= mem[rd_addr_2_i + (interfaceWidth2/dataSize-1-i)];
            end
        end
    end
end
    
endmodule