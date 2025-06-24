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
    // DIGITAL SETTING
    input [3:0] adc_ref_range_shifts,

    // ANALOG INTERFACE : SWITCH MATRIX
    input logic [numRows-1:0] PSM_VDR_SEL,
    input logic [numRows-1:0] PSM_VDR_SELB,
    input logic [numRows-1:0] PSM_VSS_SEL,
    input logic [numRows-1:0] PSM_VSS_SELB,
    input logic [numRows-1:0] PSM_VRST_SEL,
    input logic [numRows-1:0] PSM_VRST_SELB,

    input logic [numRows-1:0] NSM_VDR_SEL,
    input logic [numRows-1:0] NSM_VDR_SELB,
    input logic [numRows-1:0] NSM_VSS_SEL,
    input logic [numRows-1:0] NSM_VSS_SELB,
    input logic [numRows-1:0] NSM_VRST_SEL,
    input logic [numRows-1:0] NSM_VRST_SELB,

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
                    // $display("WR_DATA: %d, %d", WR_DATA, mem[i]);
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
logic doiroundup[numCols];


localparam signed maxValueAdc = {1'b0, {(numAdcBits-1){1'b1}}};  // 0111
localparam signed minValueAdc = {1'b1, {(numAdcBits-1){1'b0}}};  // 1000
// localparam signed maxValue = {1'b0, {(numAdcBits+adc_ref_range_shifts-1){1'b1}}};  // 0111
// localparam signed minValue = {1'b1, {(numAdcBits+adc_ref_range_shifts-1){1'b0}}};  // 1000

logic signed [31:0] maxValue;
logic signed [31:0] minValue;
always_comb begin : maxMinValues
    // The max and min values are defined by the ADC bits and the reference range shifts
    maxValue = 2**(numAdcBits+adc_ref_range_shifts-1)-1;
    minValue = 2**(numAdcBits+adc_ref_range_shifts-1) * -1;
end

always_comb begin : toMBL
    for (int j = 0; j < numCols; j++) begin
        mbl_value[j] = 0;
        for (int i = 0; i < numRows; i++) begin
            if(mem[i][j] == 1) begin
                mbl_value[j] += PSM_VDR_SEL[i];
                mbl_value[j] -= PSM_VSS_SEL[i];
            end else begin 
                mbl_value[j] += NSM_VDR_SEL[i];
                mbl_value[j] -= NSM_VSS_SEL[i];
            end
            // $display("mbl_value[%d] = %d", j, mbl_value[j]);
        end
        
        // ADC reference voltage range is divided by 2**NUM_ADC_REF_RANGE_SHIFTS
        // to follow the "best resolution"
        // The real circuit doesn't shift, it rounds.e
        if(adc_ref_range_shifts == 0) begin
            doiroundup[j] = 0;
        end else begin
            doiroundup[j] = (mbl_value[j][adc_ref_range_shifts-1]);
        end

        if (mbl_value[j] > maxValue) begin
            // $display("MBL value %d is greater than max value %d", mbl_value[j], maxValue);
            adc_out[j] = maxValueAdc;
        end else begin
            if (mbl_value[j] < minValue) begin
                // $display("MBL value %d is less than min value %d", mbl_value[j], minValue);
                adc_out[j] = minValueAdc;
            end else begin
                if (adc_ref_range_shifts > 1) begin
                    // $display("MBL value %d is between min %d and max %d", mbl_value[j], minValue, maxValue);
                    adc_out[j] = mbl_value[j][adc_ref_range_shifts +: numAdcBits] + doiroundup[j];
                end else begin
                    // ties to random
                    adc_out[j] = mbl_value[j][adc_ref_range_shifts +: numAdcBits];// + $random % (doiroundup[j] + 1);
                end
            end
        end
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