/* 

Models the ts_column for the digital parts

*/

module ts_qracc #(

    // These are defined as localparams for ease of change
    // But so that we also don't need to set values when synthesizing
    parameter numRows = 128,
    parameter numCols = 8,
    parameter numAdcBits = 4
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

    // ANALOG INTERFACE : ADC
    output logic [numAdcBits*numCols-1:0] ADC_OUT,
    input logic [numCols-1:0] NF,
    input logic [numCols-1:0] NFB,
    input logic [numCols-1:0] M2A,
    input logic [numCols-1:0] M2AB,
    input logic [numCols-1:0] R2A,
    input logic [numCols-1:0] R2AB,

    // Clock
    input logic CLK
);

// SRAM modelling
logic [numCols-1:0] mem [numRows];
always_ff @( posedge CLK ) begin :  sramModel
    if (PCH) begin
        if (WRITE) begin
            for (int i = 0; i < numRows; i++) begin
                if (WL[i]) mem[i] <= WR_DATA;
            end
        end
        if (SAEN) begin
            for (int i = 0; i < numRows; i++) begin
                if (WL[i]) SA_OUT <= mem[i];
            end
        end else begin
            SA_OUT <= 0; // Sense amplifiers have no output if SAEN isn't high
        end
    end
end

// MAC modelling
logic signed [31:0] mbl_value [numCols];
logic signed [numCols-1:0][numAdcBits-1:0] adc_out;

always_comb begin : toMBL
    for (int j = 0; j < numCols; j++) begin
        mbl_value[j] = 0;
        for (int i = 0; i < numRows; i++) begin
                mbl_value[j] += VDR_SEL[i] * mem[i][j];
        end
        adc_out[j] = mbl_value[j][6 -: numAdcBits]; // some arbitrary 4-bit subset for now
    end
    ADC_OUT <= adc_out; // auto-flattens since it's a packed array
end

endmodule