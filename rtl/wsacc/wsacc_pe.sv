module wsacc_pe #(
    parameter int dataWidth = 8,
    parameter int outputWidth = 32,
    parameter int windowElements = 9
)
( 
    input clk,
    input nrst,

    input weight_wr_en,
    input [3:0] weight_addr,
    input [dataWidth-1:0] weight_i,

    input [windowElements-1:0][dataWidth-1:0] data_i,
    output logic signed [outputWidth-1:0] data_o
);

    logic signed [windowElements-1:0][dataWidth-1:0] weight;
    logic signed [outputWidth-1:0] data_o_d;

    always_ff @(posedge clk or negedge nrst) begin
        if (!nrst) begin
            weight <= 0;
        end else begin
            if (weight_wr_en) begin
                weight[weight_addr] <= weight_i;
            end
        end
    end

    always_comb begin : multiplyAccumulate
        data_o_d = 0;
        for (int i = 0; i < windowElements; i++) begin
            // For signed multiplication, both must be signed. But, in reality, we want data_i to be unsigned.
            // So we sign-extend data_i to match the signed weight.
            data_o_d += $signed(weight[i]) * $signed({1'b0,data_i[i]}); // Assume unsigned activations for compliance
        end
    end

    assign data_o = data_o_d;

endmodule