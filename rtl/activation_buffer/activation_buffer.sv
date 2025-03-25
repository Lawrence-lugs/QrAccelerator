/*
Activations only need a fifo
*/
`timescale 1ns/1ps

module activation_buffer #(
    parameter dataSize = 8,      
    parameter depth = 1024,
    parameter addrWidth = 32,    
    parameter extInterfaceWidth = 32,
    parameter intInterfaceWidth = 256,
    localparam totalSize = depth*dataSize,
    localparam maxAddr = $clog2(depth)
) (
    input clk,
    input nrst,
    
    // External Port
    input        [extInterfaceWidth-1:0]   ext_wr_data_i,
    input ext_wr_en,
    output logic [extInterfaceWidth-1:0]   ext_rd_data_o,
    input [addrWidth-1:0] ext_addr_i,

    // Internal Port
    input        [intInterfaceWidth-1:0]   int_wr_data_i,
    input int_wr_en,
    output logic [intInterfaceWidth-1:0]   int_rd_data_o,
    input [addrWidth-1:0] int_addr_i
);

//-----------------------------------
// Signals
//-----------------------------------

logic [addrWidth-1:0] fmap_ptr_1;
logic [addrWidth-1:0] fmap_ptr_2;

//-----------------------------------
// Modules
//-----------------------------------
ram_2wr #(
    .addrWidth      (addrWidth),
    .dataSize       (dataSize),
    
    .interfaceWidth1(extInterfaceWidth), // 32b
    .interfaceWidth2(intInterfaceWidth), // 256b
    
    .depth          (depth)
) u_act_memory (
    .clk            (clk),
    .nrst           (nrst),

    .wr_en_1_i      (ext_wr_en),
    .addr_1_i       (ext_addr_i),
    .wr_data_1_i    (ext_wr_data_i),
    .rd_data_1_o    (ext_rd_data_o),

    .wr_en_2_i      (int_wr_en),
    .addr_2_i       (int_addr_i),
    .wr_data_2_i    (int_wr_data_i),
    .rd_data_2_o    (int_rd_data_o)
);

//-----------------------------------
// Logic
//-----------------------------------



endmodule