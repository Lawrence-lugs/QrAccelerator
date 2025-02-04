/* 

Models the ts_column for the digital parts
Just qracc with numCols = 1

*/

module ts_column #(

    // These are defined as localparams for ease of change
    // But so that we also don't need to set values when synthesizing
    localparam numRows = 128,
    parameter numCols = 1,
    localparam numAdcBits = 4
) (
    // ANALOG INTERFACE : SWITCH MATRIX
    input logic [numRows-1:0] VDR_SEL,
    input logic [numRows-1:0] VDR_SELB,
    input logic [numRows-1:0] VSS_SEL,
    input logic [numRows-1:0] VSS_SELB,
    input logic [numRows-1:0] VRST_SEL,
    input logic [numRows-1:0] VRST_SELB,

    // ANALOG INTERFACE : SRAM
    output logic [numCols-1:0] SA_OUT,
    input logic [numRows-1:0] WL,
    input logic [numCols-1:0] PCH,
    input logic [numCols-1:0] WR_DATA,
    input logic [numCols-1:0] WRITE,
    input logic [numCols-1:0] CSEL,
    input logic [numCols-1:0] SAEN,

    // ANALOG INTERF2ACE : ADC
    output logic [15*numCols-1:0] ADC_OUT,
    input logic [numCols-1:0] NF,
    input logic [numCols-1:0] NFB,
    input logic [numCols-1:0] M2A,
    input logic [numCols-1:0] M2AB,
    input logic [numCols-1:0] R2A,
    input logic [numCols-1:0] R2AB,

    // Clock
    input logic CLK
);

endmodule