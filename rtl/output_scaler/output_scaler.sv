/*

Implements output scaling per
<insert link of tflite paper>

Verilator has a lot of warnings, but this code has previously been tested and synthesized on VCS.

*/
`timescale 1ns/1ps

module output_scaler #(
    parameter inputWidth = 20,
    parameter maxOutputWidth = 8,
    // Static Parameters, mostly
    parameter fixedPointBits = 16,
    parameter shiftBits = 16
) (
    input clk, nrst,

    input signed [inputWidth-1:0] wx_i,
    output logic signed [maxOutputWidth-1:0] y_o,

    input [fixedPointBits-1:0] output_scale,
    input [shiftBits-1:0] output_shift,
    input [maxOutputWidth-1:0] output_offset,
    input [31:0] output_bias,

    input cfg_unsigned,
    input [3:0] cfg_output_bits
);

logic signed [maxOutputWidth-1:0] saturateHigh;
logic signed [maxOutputWidth-1:0] saturateLow;
logic signed [inputWidth-1:0] compareHigh;
logic signed [inputWidth-1:0] compareLow;

logic signed [31:0] wx_i_extended;
logic signed [31:0] wx_i_biased;
logic signed [31:0] scaled_wx;
logic signed [31:0] scaled_wx_fpshift;
logic signed [31:0] scaled_wx_shifted;
logic signed [31:0] scaled_wx_presat;
logic signed [maxOutputWidth-1:0] y_o_d;

assign y_o = y_o_d;

always_comb begin : saturationLimits

    // Saturation limits
    if (cfg_unsigned) begin
        saturateHigh = 2**cfg_output_bits - 1;  // 0111...111
        saturateLow = 0;  // 0000...000
        compareHigh = { {inputWidth-maxOutputWidth{1'b0}}, saturateHigh };
        compareLow = { {inputWidth-maxOutputWidth{1'b0}}, saturateLow };
    end else begin
        saturateHigh = 2**(cfg_output_bits-1) - 1;  // 0111...111
        saturateLow = 2**(cfg_output_bits-1);  // 1000...000
        compareHigh = { {inputWidth-maxOutputWidth{1'b0}}, saturateHigh };
        compareLow = { {inputWidth-maxOutputWidth{1'b1}}, saturateLow };
    end
    
end

always_comb begin : fpMultComb
    // We have to explicitly implement this as unsigned multiplications
    // Because signed * unsigned asymmetric multiplication is ambiguous
    // Note: signed * unsigned --> unsigned * unsigned
    // All of this is scary when switching simulators.

    wx_i_extended = { {32-inputWidth{wx_i[inputWidth-1]}}, wx_i };
    wx_i_biased = wx_i_extended + output_bias;
    
    if (wx_i_biased[inputWidth-1] == 1) begin
        // wx_i_biased is negative
        scaled_wx = ~(31'( inputWidth'(~wx_i_biased+1) * output_scale)) + 1;
    end else begin
        // wx_i_biased is positive
        scaled_wx = 31'(wx_i_biased * output_scale);
    end

    // It doesn't do arithmetic shift unless $signed for some reason
    // But it doesn't matter for fpshift because it's just a bit drop
    scaled_wx_fpshift = scaled_wx >>> fixedPointBits;
    
    // Arithmetic shift divide by 2**n rounds down towards -infty
    // This turns negatives wrong vs python, so we have to explicitly state things
    // if (scaled_wx_fpshift[inputWidth-1] == 1) begin
    //     scaled_wx_shifted = ($signed(scaled_wx_fpshift) >>> output_shift) + 1;
    // end else begin
    scaled_wx_shifted = $signed(scaled_wx_fpshift) >>> output_shift;
    // end

    scaled_wx_presat = scaled_wx_shifted + {24'b0,output_offset};

    // Saturating clipping
    if ($signed(scaled_wx_presat) > compareHigh) begin // Does this auto sign-extend for the comparison?
        y_o_d = saturateHigh;
    end
    else if ($signed(scaled_wx_presat) < compareLow) begin // Does this auto sign-extend?
        y_o_d = saturateLow;
    end
    else begin
        y_o_d = scaled_wx_presat[maxOutputWidth-1:0];
    end
end

endmodule