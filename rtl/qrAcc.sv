module ts_column (
    // ANALOG INTERFACE : SWITCH MATRIX
    input logic [127:0] VDR_SEL,
    input logic [127:0] VDR_SELB,
    input logic [127:0] VSS_SEL,
    input logic [127:0] VSS_SELB,
    input logic [127:0] VRST_SEL,
    input logic [127:0] VRST_SELB,

    // ANALOG INTERFACE : SRAM
    output logic [0:0] SA_OUT,
    input logic [127:0] WL,
    input logic [0:0] PCH,
    input logic [0:0] WR_DATA,
    input logic [0:0] WRITE,
    input logic [0:0] CSEL,
    input logic [0:0] SAEN,

    // ANALOG INTERFACE : ADC
    output logic [3:0] ADC_OUT,
    input logic [0:0] NF,
    input logic [0:0] NFB,
    input logic [0:0] M2A,
    input logic [0:0] M2AB,
    input logic [0:0] R2A,
    input logic [0:0] R2AB,

    // Clock
    input logic CLK
);
endmodule