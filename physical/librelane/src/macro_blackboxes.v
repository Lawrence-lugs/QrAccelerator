// Synthesis blackboxes for the hardened macros used by the top flow.
// The real views come from the LibreLane MACROS configuration.

(* blackbox *)
module output_scaler_group (
    input  logic clk,
    input  logic nrst,
    input  logic signed [8*24-1:0] wx_i,
    output logic signed [8*8-1:0] y_o,
    input  logic [8*16-1:0] scale_i,
    input  logic [8*4-1:0]  shift_i,
    input  logic [8*8-1:0]  offset_i,
    input  logic [8*32-1:0] bias_i,
    input  logic cfg_unsigned,
    input  logic [3:0] cfg_output_bits
);
endmodule

(* blackbox *)
module feature_loader #(
    parameter inputWidth = 256,
    parameter addrWidth = 8,
    parameter elementWidth = 8,
    parameter numElements = 128
) (
    input  logic clk,
    input  logic nrst,
    input  logic [inputWidth-1:0] data_i,
    input  logic [addrWidth-1:0] addr_i,
    input  logic wr_en,
    output logic [numElements-1:0][elementWidth-1:0] data_o,
    input  logic [15:0] mask_start,
    input  logic [15:0] mask_end
);
endmodule

(* blackbox *)
module ram_2w2r #(
    parameter addrWidth = 32,
    parameter dataSize = 8,
    parameter interfaceWidth1 = 32,
    parameter interfaceWidth2 = 256,
    parameter depth = 1024
) (
    input  logic clk,
    input  logic nrst,

    input  logic wr_en_1_i,
    input  logic [addrWidth-1:0] wr_addr_1_i,
    input  logic [interfaceWidth1-1:0] wr_data_1_i,
    input  logic rd_en_1_i,
    input  logic [addrWidth-1:0] rd_addr_1_i,
    output logic [interfaceWidth1-1:0] rd_data_1_o,

    input  logic wr_en_2_i,
    input  logic [addrWidth-1:0] wr_addr_2_i,
    input  logic [interfaceWidth2-1:0] wr_data_2_i,
    input  logic rd_en_2_i,
    input  logic [addrWidth-1:0] rd_addr_2_i,
    output logic [interfaceWidth2-1:0] rd_data_2_o
);
endmodule
