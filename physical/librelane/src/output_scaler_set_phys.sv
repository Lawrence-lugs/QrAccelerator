// Physical replacement for rtl/output_scaler/output_scaler_set.sv.
//
// The weight memory and write-address logic are unchanged.  The 256 lane
// instances are replaced by 32 output_scaler_group macros, each containing
// eight output_scaler lanes.  This file is top glue, not a hardened macro.
//
// The existing shift_w_addr assignment is preserved deliberately: the physical
// netlist must match the RTL behaviour, including its current address update.

module output_scaler_set #(
    parameter numElements = 64,
    parameter inputWidth = 20,
    parameter outputWidth = 8,
    parameter scaleBits = 16,
    parameter shiftBits = 4,
    parameter offsetBits = 8
) (
    input clk, nrst,

    input signed [numElements-1:0][inputWidth-1:0] wx_i,
    output logic signed [numElements-1:0][outputWidth-1:0] y_o,

    input scale_w_en_i,
    input [scaleBits-1:0] scale_w_data_i,

    input shift_w_en_i,
    input [shiftBits-1:0] shift_w_data_i,

    input offset_w_en_i,
    input [offsetBits-1:0] offset_w_data_i,

    input bias_w_en_i,
    input [31:0] bias_w_data_i,

    input cfg_unsigned,
    input [3:0] cfg_output_bits
);

localparam addrWidth = $clog2(numElements);
localparam numGroups = numElements / 8;

logic [scaleBits-1:0] output_scale [numElements];
logic signed [shiftBits-1:0] output_shift [numElements];
logic signed [offsetBits-1:0] output_offset [numElements];
logic signed [31:0] output_bias [numElements];
logic [addrWidth-1:0] scale_w_addr;
logic [addrWidth-1:0] shift_w_addr;
logic [addrWidth-1:0] offset_w_addr;
logic [addrWidth-1:0] bias_w_addr;

always_ff @( posedge clk or negedge nrst) begin : scalerMemory
    if (!nrst) begin
        for (int i = 0; i < numElements; i = i + 1) begin
            output_scale[i] = 0;
            output_shift[i] = 0;
            output_offset[i] = 0;
            output_bias[i] = 0;
        end
        scale_w_addr <= 0;
        shift_w_addr <= 0;
        offset_w_addr <= 0;
        bias_w_addr <= 0;
    end else begin
        if (scale_w_en_i) begin
            output_scale[scale_w_addr] <= scale_w_data_i;
            scale_w_addr <= scale_w_addr + 1;
        end
        if (shift_w_en_i) begin
            output_shift[shift_w_addr] <= shift_w_data_i;
            shift_w_addr <= scale_w_addr + 1;
        end
        if (offset_w_en_i) begin
            output_offset[offset_w_addr] <= offset_w_data_i;
            offset_w_addr <= offset_w_addr + 1;
        end
        if (bias_w_en_i) begin
            output_bias[bias_w_addr] <= bias_w_data_i;
            bias_w_addr <= bias_w_addr + 1;
        end
    end
end

generate
    genvar g, k;
    for (g = 0; g < numGroups; g = g + 1) begin : g_group
        wire [8*inputWidth-1:0] group_wx;
        wire [8*outputWidth-1:0] group_y;
        wire [8*scaleBits-1:0] group_scale;
        wire [8*shiftBits-1:0] group_shift;
        wire [8*offsetBits-1:0] group_offset;
        wire [8*32-1:0] group_bias;

        for (k = 0; k < 8; k = k + 1) begin : g_lane
            assign group_wx[k*inputWidth +: inputWidth] = wx_i[g*8 + k];
            assign group_scale[k*scaleBits +: scaleBits] = output_scale[g*8 + k];
            assign group_shift[k*shiftBits +: shiftBits] = output_shift[g*8 + k];
            assign group_offset[k*offsetBits +: offsetBits] = output_offset[g*8 + k];
            assign group_bias[k*32 +: 32] = output_bias[g*8 + k];
            assign y_o[g*8 + k] = group_y[k*outputWidth +: outputWidth];
        end

        output_scaler_group u_output_scaler_group (
            .clk(clk),
            .nrst(nrst),
            .wx_i(group_wx),
            .y_o(group_y),
            .scale_i(group_scale),
            .shift_i(group_shift),
            .offset_i(group_offset),
            .bias_i(group_bias),
            .cfg_unsigned(cfg_unsigned),
            .cfg_output_bits(cfg_output_bits)
        );
    end
endgenerate

endmodule
