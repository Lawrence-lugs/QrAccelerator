/*

Implements output scaling per
<insert link of tflite paper>

*/

module output_scaler #(
    parameter numElements = 4,
    parameter elementWidth = 20,
    parameter outputWidth = 8,
    // Static Parameters, mostly
    parameter fixedPointBits = 16,
    parameter shiftBits = 16
) (
    input clk, nrst,

    input signed [numElements-1:0][elementWidth-1:0] wx_i,
    output logic signed [numElements-1:0][outputWidth-1:0] y_o,

    input [fixedPointBits-1:0] output_scale,
    input [shiftBits-1:0] output_shift
);

localparam scaledWidth = elementWidth+fixedPointBits;
localparam signed saturateHigh = {1'b0, {(outputWidth-1){1'b1}}};  // 0111...111
localparam signed saturateLow = {1'b1, {(outputWidth-1){1'b0}}};  // 1000...000
// Sign-extended versions of saturateHigh and saturateLow
localparam signed compareHigh = { {(elementWidth-outputWidth+1){1'b0}} , {(outputWidth-1){1'b1}} };
localparam signed compareLow = { {(elementWidth-outputWidth+1){1'b1}} , {(outputWidth-1){1'b0}} };

logic signed [numElements-1:0][scaledWidth-1:0] scaled_wx;
logic signed [numElements-1:0][elementWidth-1:0] scaled_wx_fpshift;
logic signed [numElements-1:0][elementWidth-1:0] scaled_wx_shifted;
logic signed [numElements-1:0][outputWidth-1:0] y_o_d;

assign y_o = y_o_d;

always_comb begin : fpMultComb
    for (int i = 0; i < numElements; i = i + 1) begin
        // We have to explicitly implement this as unsigned multiplications
        // Because signed * unsigned asymmetric multiplication is ambiguous
        // Note: signed * unsigned --> unsigned * unsigned
        // All of this is scary when switching simulators.
        
        if (wx_i[i][elementWidth-1] == 1) begin
            // wx_i is negative
            scaled_wx[i] = ~(scaledWidth'( elementWidth'(~wx_i[i]+1) * output_scale)) + 1;
        end else begin
            // wx_i is positive
            scaled_wx[i] = scaledWidth'(wx_i[i] * output_scale);
        end


        // It doesn't do arithmetic shift unless $signed for some reason
        // But it doesn't matter for fpshift because it's just a bit drop
        scaled_wx_fpshift[i] = scaled_wx[i] >>> fixedPointBits;
        
        // Arithmetic shift divide by 2**n rounds down towards -infty
        // This turns negatives wrong vs python, so we have to explicitly state things
        if (scaled_wx_fpshift[i][elementWidth-1] == 1) begin
            scaled_wx_shifted[i] = ($signed(scaled_wx_fpshift[i]) >>> output_shift) + 1;
        end else begin
            scaled_wx_shifted[i] = $signed(scaled_wx_fpshift[i]) >>> output_shift;
        end

        // Saturating clipping
        if ($signed(scaled_wx_shifted[i]) > compareHigh) begin // Does this auto sign-extend for the comparison?
            y_o_d[i] = saturateHigh;
        end
        else if ($signed(scaled_wx_shifted[i]) < compareLow) begin // Does this auto sign-extend?
            y_o_d[i] = saturateLow;
        end
        else begin
            y_o_d[i] = scaled_wx_shifted[i][outputWidth-1:0];
        end
    end
end

endmodule