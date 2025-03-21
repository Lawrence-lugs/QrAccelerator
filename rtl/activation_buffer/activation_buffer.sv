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
    input logic clk,
    input logic nrst,
    
    // Interface to External
    input        [extInterfaceWidth-1:0]   ext_wr_data_i,
    input logic ctrl_ext_wr_en,
    output logic [extInterfaceWidth-1:0]   ext_rd_data_o,
    input logic ctrl_ext_rd_en,

    // Interface to Internal 
    input        [intInterfaceWidth-1:0]   int_wr_data_i,
    input logic ctrl_int_wr_en,
    output logic [intInterfaceWidth-1:0]   int_rd_data_o,
    input logic ctrl_int_rd_en,
    
    // For Debugging
    output logic [addrWidth-1:0]        write_head_snoop
);

//-----------------------------------
// Signals
//-----------------------------------

logic [addrWidth-1:0] head;

//-----------------------------------
// Modules
//-----------------------------------
ram_2w1r #(
    .addrWidth1      (addrWidth),
    .addrWidth2      (addrWidth),
    .dataSize       (dataSize),
    .interfaceWidth1(extInterfaceWidth), // 32b
    .interfaceWidth2(intInterfaceWidth), // 256b
    .depth          (depth)
) u_ram (
    .clk            (clk),
    .nrst           (nrst),

    .wr_en_1_i      (ctrl_ext_wr_en),
    .wr_addr_1_i    (head),
    .wr_data_1_i    (ext_wr_data_i),

    .wr_en_2_i      (ctrl_int_wr_en),
    .wr_addr_2_i    (head),
    .wr_data_2_i    (int_wr_data_i),
    
    .rd_en_i        (ctrl_rd_en),
    .rd_data_o      (rd_data_o),
    .rd_addr_i      (tail)
);

//-----------------------------------
// Control Logic
//-----------------------------------

always_ff @( posedge clk or negedge nrst ) begin : headsControl
    if (!nrst) begin
        head <= 0;
    end else begin
        if (ctrl_wr_en) begin
            if (head == maxAddr - 1) begin
                head <= 0;
            end else begin
                head <= head + 1;
            end
        end
    end
end

always_comb begin : headsAssigns
    write_head_snoop = head;
end

endmodule