// Synthesis view of the IHP SG13G2 2-port 1024x32 SRAM macro.
// Simulation uses the PDK behavioural model instead of this file.

(* blackbox *)
module RM_IHPSG13_2P_1024x32_c2_bm_bist (
    input  logic A_CLK,
    input  logic A_MEN,
    input  logic A_WEN,
    input  logic A_REN,
    input  logic [9:0] A_ADDR,
    input  logic [31:0] A_DIN,
    input  logic A_DLY,
    output logic [31:0] A_DOUT,
    input  logic [31:0] A_BM,
    input  logic A_BIST_CLK,
    input  logic A_BIST_EN,
    input  logic A_BIST_MEN,
    input  logic A_BIST_WEN,
    input  logic A_BIST_REN,
    input  logic [9:0] A_BIST_ADDR,
    input  logic [31:0] A_BIST_DIN,
    input  logic [31:0] A_BIST_BM,

    input  logic B_CLK,
    input  logic B_MEN,
    input  logic B_WEN,
    input  logic B_REN,
    input  logic [9:0] B_ADDR,
    input  logic [31:0] B_DIN,
    input  logic B_DLY,
    output logic [31:0] B_DOUT,
    input  logic [31:0] B_BM,
    input  logic B_BIST_CLK,
    input  logic B_BIST_EN,
    input  logic B_BIST_MEN,
    input  logic B_BIST_WEN,
    input  logic B_BIST_REN,
    input  logic [9:0] B_BIST_ADDR,
    input  logic [31:0] B_BIST_DIN,
    input  logic [31:0] B_BIST_BM
);
endmodule
