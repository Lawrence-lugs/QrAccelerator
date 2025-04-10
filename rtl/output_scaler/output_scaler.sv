/*

Implements output scaling per
<insert link of tflite paper>

Verilator has a lot of warnings, but this code has previously been tested and synthesized on VCS.

*/
`timescale 1ns/1ps

module output_scaler #(
    parameter inputWidth = 20,
    parameter outputWidth = 8,
    // Static Parameters, mostly
    parameter fixedPointBits = 16,
    parameter shiftBits = 16
) (
    input clk, nrst,

    input signed [inputWidth-1:0] wx_i,
    output logic signed [outputWidth-1:0] y_o,

    input [fixedPointBits-1:0] output_scale,
    input [shiftBits-1:0] output_shift
);

localparam signed saturateHigh = {1'b0, {(outputWidth-1){1'b1}}};  // 0111...111
localparam signed saturateLow = {1'b1, {(outputWidth-1){1'b0}}};  // 1000...000
// Sign-extended versions of saturateHigh and saturateLow
localparam signed compareHigh = { {(inputWidth-outputWidth+1){1'b0}} , {(outputWidth-1){1'b1}} };
localparam signed compareLow = { {(inputWidth-outputWidth+1){1'b1}} , {(outputWidth-1){1'b0}} };

logic signed [31:0] scaled_wx;
logic signed [31:0] scaled_wx_fpshift;
logic signed [31:0] scaled_wx_shifted;
logic signed [outputWidth-1:0] y_o_d;

assign y_o = y_o_d;

always_comb begin : fpMultComb
    // We have to explicitly implement this as unsigned multiplications
    // Because signed * unsigned asymmetric multiplication is ambiguous
    // Note: signed * unsigned --> unsigned * unsigned
    // All of this is scary when switching simulators.
    
    if (wx_i[inputWidth-1] == 1) begin
        // wx_i is negative
        scaled_wx = ~(31'( inputWidth'(~wx_i+1) * output_scale)) + 1;
    end else begin
        // wx_i is positive
        scaled_wx = 31'(wx_i * output_scale);
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

    // Saturating clipping
    if ($signed(scaled_wx_shifted) > compareHigh) begin // Does this auto sign-extend for the comparison?
        y_o_d = saturateHigh;
    end
    else if ($signed(scaled_wx_shifted) < compareLow) begin // Does this auto sign-extend?
        y_o_d = saturateLow;
    end
    else begin
        y_o_d = scaled_wx_shifted[outputWidth-1:0];
    end
end

endmodule