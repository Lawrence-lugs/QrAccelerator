// Physical ACTMEM implementation for the ModelMem path.
//
// This module replaces rtl/memory/ram_2w2r.sv in the physical file list.  It has
// the same port list and parameter names as the behavioural model, so qr_acc_top
// does not change.  The internal implementation uses 1024x32 two-port SRAM
// macros: eight column banks and eight row banks for 256 KiB.

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

    actmem_2w2r_ihp #(
        .addrWidth(addrWidth),
        .dataSize(dataSize),
        .interfaceWidth1(interfaceWidth1),
        .interfaceWidth2(interfaceWidth2),
        .depth(depth),
        .MACRO_ROWS(1024)
    ) u_impl (
        .clk(clk),
        .nrst(nrst),

        .wr_en_1_i(wr_en_1_i),
        .wr_addr_1_i(wr_addr_1_i),
        .wr_data_1_i(wr_data_1_i),
        .rd_en_1_i(rd_en_1_i),
        .rd_addr_1_i(rd_addr_1_i),
        .rd_data_1_o(rd_data_1_o),

        .wr_en_2_i(wr_en_2_i),
        .wr_addr_2_i(wr_addr_2_i),
        .wr_data_2_i(wr_data_2_i),
        .rd_en_2_i(rd_en_2_i),
        .rd_addr_2_i(rd_addr_2_i),
        .rd_data_2_o(rd_data_2_o)
    );

endmodule
