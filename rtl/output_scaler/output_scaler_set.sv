//
//
// A set of output scalers with different scales
//
//
`timescale 1ns / 1ps

module output_scaler_set #(
    parameter numElements = 64,
    parameter inputWidth = 20,
    parameter outputWidth = 8,
    // Changing these will change the algorithm behavior
    parameter scaleBits = 16, 
    parameter shiftBits = 4    
) (
    input clk, nrst,

    input signed [inputWidth-1:0] wx_i [numElements],
    output logic signed [outputWidth-1:0] y_o [numElements],

    // Scaler memory inputs
    input scale_w_en_i,
    input [scaleBits-1:0] scale_w_data_i,

    // Shift memory inputs
    input shift_w_en_i,
    input [shiftBits-1:0] shift_w_data_i
);

// Parameters
localparam addrWidth = $clog2(numElements);

// Registers
logic signed [scaleBits-1:0] output_scale [numElements];
logic signed [shiftBits-1:0] output_shift [numElements];
logic [addrWidth-1:0] scale_w_addr;
logic [addrWidth-1:0] shift_w_addr;

// Modules
always_ff @( posedge clk or negedge nrst) begin : scalerMemory
    if (!nrst) begin
        for (int i = 0; i < numElements; i = i + 1) begin
            output_scale[i] <= 0;
            output_shift[i] <= 0;
        end
        scale_w_addr <= 0;
        shift_w_addr <= 0;
    end else begin
        if (scale_w_en_i) begin
            output_scale[scale_w_addr] <= scale_w_data_i;
            scale_w_addr <= (scale_w_addr < numElements) ? scale_w_addr + 1 : 0;
        end
        if (shift_w_en_i) begin
            output_shift[shift_w_addr] <= shift_w_data_i;
            shift_w_addr <= (shift_w_addr < numElements) ? shift_w_addr + 1 : 0;
        end
    end
end

generate
    genvar i;
    for (i = 0; i < numElements; i = i + 1) begin : oScalerInstances
        output_scaler #(
            .inputWidth(inputWidth),
            .outputWidth(outputWidth),
            .fixedPointBits(scaleBits),
            .shiftBits(shiftBits)
        ) u_output_scaler (
            .clk(clk),
            .nrst(nrst),
            .wx_i(wx_i[i]),
            .y_o(y_o[i]),
            .output_scale(output_scale[i]),
            .output_shift(output_shift[i])
        );
    end
endgenerate

endmodule