`timescale 1ns/1ps

module tb_shift_add_tree #(
    parameter int numPlanes = 8,
    parameter int numOutputs = 1,
    parameter int partialBits = 4,
    parameter [3:0] weightBits = 4'd1,
    parameter bit weightSigned = 1'b0
) (
);
    logic [3:0] weight_bits_i;
    logic weight_signed_i;
    logic signed [numPlanes-1:0][numOutputs-1:0][partialBits-1:0] partial_i;
    logic signed [numOutputs-1:0][partialBits+numPlanes-1:0] sum_o;

    shift_add_tree #(
        .numPlanes(numPlanes),
        .numOutputs(numOutputs),
        .partialBits(partialBits)
    ) dut (
        .weight_bits_i(weight_bits_i),
        .weight_signed_i(weight_signed_i),
        .partial_i(partial_i),
        .sum_o(sum_o)
    );

    int fail_count = 0;

    task automatic check_case(
        input logic signed [partialBits-1:0] p0,
        input logic signed [partialBits-1:0] p1,
        input logic signed [partialBits-1:0] p2,
        input logic signed [partialBits-1:0] p3,
        input logic signed [partialBits-1:0] p4,
        input logic signed [partialBits-1:0] p5,
        input logic signed [partialBits-1:0] p6,
        input logic signed [partialBits-1:0] p7
    );
        logic signed [numOutputs-1:0][partialBits+numPlanes-1:0] golden;
        int b, o;
        logic signed [partialBits-1:0] pval;
        logic signed [partialBits+numPlanes-1:0] term;
        int B;
        logic signed [partialBits-1:0] pvec [numPlanes-1:0];
        begin
            pvec[0] = p0; pvec[1] = p1; pvec[2] = p2; pvec[3] = p3;
            pvec[4] = p4; pvec[5] = p5; pvec[6] = p6; pvec[7] = p7;

            weight_bits_i = weightBits;
            weight_signed_i = weightSigned;
            for (b = 0; b < numPlanes; b++) begin
                partial_i[b][0] = pvec[b];
            end
            #1;
            B = (weightBits == 0) ? 1 : weightBits;
            golden = '0;
            for (b = 0; b < numPlanes; b++) begin
                if (b < B) begin
                    pval = pvec[b];
                    term = $signed({{(partialBits+numPlanes-1-partialBits){pval[partialBits-1]}}, pval}) << b;
                    if (weightSigned && (b == B - 1))
                        term = -term;
                    golden[0] += term;
                end
            end
            if (sum_o[0] !== golden[0]) begin
                $display("MISMATCH: weightBits=%0d weightSigned=%0d sum_o=%0d golden=%0d",
                         weightBits, weightSigned, sum_o[0], golden[0]);
                fail_count++;
            end
        end
    endtask

    initial begin
        check_case(-4,  0,  0,  0,  0,  0,  0,  0);
        check_case( 7,  0,  0,  0,  0,  0,  0,  0);
        check_case( 0,  0,  0,  0,  0,  0,  0,  0);
        check_case(-4,  3,  0,  0,  0,  0,  0,  0);
        check_case(-4,  3,  0,  0,  0,  0,  0,  0);
        check_case( 1,  1,  1,  1,  0,  0,  0,  0);
        check_case( 1,  1,  1,  1,  1,  1,  1,  1);
        check_case(-8,  0,  0,  0,  0,  0,  0,  0);
        check_case( 7,  0,  0,  0,  0,  0,  0,  0);

        if (fail_count == 0) begin
            $display("TB_PASS");
        end else begin
            $display("TB_FAIL");
            $fatal(1, "Testbench failed with %0d mismatches", fail_count);
        end
    end
endmodule
