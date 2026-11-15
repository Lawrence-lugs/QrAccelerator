// Combine per-plane partial sums by shifting each plane b left by b bits.
// Planes b >= weight_bits_i contribute zero (weight_bits_i == 0 treated as B=1).
// If weight_signed_i == 1, the MSB plane (b == B-1) is negated before adding.
// For B=1 and unsigned, sum_o equals partial_i[0] sign-extended exactly.
module shift_add_tree #(
    parameter int numPlanes = 8,
    parameter int numOutputs = 32,
    parameter int partialBits = 4
) (
    input  logic [3:0]                      weight_bits_i,
    input  logic                            weight_signed_i,
    input  logic signed [numPlanes-1:0][numOutputs-1:0][partialBits-1:0] partial_i,
    output logic signed [numOutputs-1:0][partialBits+numPlanes-1:0]     sum_o
);
    localparam int sumBits = partialBits + numPlanes - 1;

    logic [3:0] B;
    assign B = (weight_bits_i == 4'd0) ? 4'd1 : weight_bits_i;

    logic signed [sumBits-1:0] terms [numPlanes-1:0][numOutputs-1:0];

    genvar b, o;
    generate
        for (b = 0; b < numPlanes; b++) begin : g_plane
            for (o = 0; o < numOutputs; o++) begin : g_out
                always_comb begin
                    if (b >= B) begin
                        terms[b][o] = '0;
                    end else begin
                        terms[b][o] = $signed({{(sumBits-partialBits){partial_i[b][o][partialBits-1]}}, partial_i[b][o]}) << b;
                        if (weight_signed_i && (b == B - 1)) begin
                            terms[b][o] = -terms[b][o];
                        end
                    end
                end
            end
        end
    endgenerate

    generate
        for (o = 0; o < numOutputs; o++) begin : g_sum
            always_comb begin
                sum_o[o] = '0;
                for (int b = 0; b < numPlanes; b++) begin
                    sum_o[o] += terms[b][o];
                end
            end
        end
    endgenerate

endmodule
