// Eight output_scaler lanes hardened as one macro.  The scaler weight memory
// stays in the physical output_scaler_set glue, so this wrapper only groups the
// lane datapaths and exposes the eight lanes' weight inputs.

module output_scaler_group (
    input  logic clk,
    input  logic nrst,

    input  logic signed [8*24-1:0] wx_i,
    output logic signed [8*8-1:0] y_o,

    input  logic [8*16-1:0] scale_i,
    input  logic [8*4-1:0]  shift_i,
    input  logic [8*8-1:0]  offset_i,
    input  logic [8*32-1:0] bias_i,

    input  logic cfg_unsigned,
    input  logic [3:0] cfg_output_bits
);

    generate
        for (genvar g = 0; g < 8; g++) begin : g_lane
            output_scaler #(
                .inputWidth(24),
                .maxOutputWidth(8),
                .fixedPointBits(16),
                .shiftBits(4)
            ) u_output_scaler (
                .clk(clk),
                .nrst(nrst),
                .wx_i(wx_i[g*24 +: 24]),
                .y_o(y_o[g*8 +: 8]),
                .output_scale(scale_i[g*16 +: 16]),
                .output_shift(shift_i[g*4 +: 4]),
                .output_offset(offset_i[g*8 +: 8]),
                .output_bias(bias_i[g*32 +: 32]),
                .cfg_unsigned(cfg_unsigned),
                .cfg_output_bits(cfg_output_bits)
            );
        end
    endgenerate

endmodule
