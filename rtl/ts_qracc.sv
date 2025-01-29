/* 

Models the ts_column for the digital parts

*/

module ts_qracc #(

    // These are defined as localparams for ease of change
    // But so that we also don't need to set values when synthesizing
    parameter numRows = 128,
    parameter numCols = 8,
    parameter numAdcBits = 4,
    localparam compCount = (2**numAdcBits)-1 // An ADC only has 2^numAdcBits-1 comparators
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
    input logic PCH,
    input logic [numCols-1:0] WR_DATA,
    input logic WRITE,
    input logic [numCols-1:0] CSEL,
    input logic SAEN,

    // ANALOG INTERFACE : ADC
    output logic [compCount*numCols-1:0] ADC_OUT,
    input logic NF,
    input logic NFB,
    input logic M2A,
    input logic M2AB,
    input logic R2A,
    input logic R2AB,

    // Clock
    input logic CLK
);

// SRAM modelling
logic [numCols-1:0] mem [numRows];
always_ff @( posedge CLK ) begin :  sramModel
    if (PCH) begin
        if (WRITE) begin
            for (int i = 0; i < numRows; i++) begin
                if (WL[i]) begin 
                    mem[i] <= WR_DATA;
                    $display("WR_DATA: %d, %d", WR_DATA, mem[i]);
                end
            end
        end
    end
end
// SA output is not registered
always_comb begin : readModel
    if (PCH && SAEN) begin
        for (int i = 0; i < numRows; i++) begin
            if (WL[i]) SA_OUT = mem[i];
        end
    end else begin
        SA_OUT = 0;
    end
end


// MAC modelling
logic signed [31:0] mbl_value [numCols];
logic signed [numAdcBits-1:0] adc_out [numCols];
logic signed [numCols-1:0][compCount-1:0] comp_out;

localparam signed maxValue = {1'b0, {(numAdcBits+`NUM_ADC_REF_RANGE_SHIFTS-1){1'b1}}};  // 0111
localparam signed minValue = {1'b1, {(numAdcBits+`NUM_ADC_REF_RANGE_SHIFTS-1){1'b0}}};  // 1000

always_comb begin : toMBL
    for (int j = 0; j < numCols; j++) begin
        mbl_value[j] = 0;
        for (int i = 0; i < numRows; i++) begin
            // BINARY MODE
            // mbl_value[j] += VDR_SEL[i] * mem[i][j];
            // mbl_value[j] -= VSS_SEL[i] * mem[i][j];
            // BIPOLAR MODE
            if(mem[i][j] == 1) begin
                mbl_value[j] += VDR_SEL[i];
                mbl_value[j] -= VSS_SEL[i];
            end else begin 
                mbl_value[j] -= VDR_SEL[i];
                mbl_value[j] += VSS_SEL[i];
            end
        end
        
        // ADC reference voltage range is divided by 2**NUM_ADC_REF_RANGE_SHIFTS
        // to follow the "best resolution"
        adc_out[j] = mbl_value[j][`NUM_ADC_REF_RANGE_SHIFTS +: numAdcBits];
        if (mbl_value[j] > maxValue) begin
            adc_out[j] = maxValue;
        end
        if (mbl_value[j] < minValue) begin
            adc_out[j] = minValue;
        end

        // The real circuit doesn't shift, it rounds.

    end
    
    // Decode the ADC output
    for (int j = 0; j < numCols; j++) begin
        for (int i = 0; i < compCount; i++) begin
            comp_out[j][i] = ($signed(adc_out[j])+8 > i) ? 1 : 0;
        end
    end

    ADC_OUT <= comp_out;
end

endmodule