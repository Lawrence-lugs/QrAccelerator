


module afl_element #(
    parameter elementWidth = 4
) (
    input clk, nrst,

    input [elementWidth-1:0] horizontal_i,
    input [elementWidth-1:0] diagonal_i,
    input [elementWidth-1:0] vertical_i,

    output [elementWidth-1:0] feature_o,

    input [1:0] load_direction_i // 00 - No, 10 - Horizontal, 01 - Vertical, 11 - Diagonal
);

logic [elementWidth-1:0] mem;

always_ff @( posedge clk or negedge nrst ) begin : mainLogic
    if (!nrst) begin
        mem <= 0;
    end else begin
        case (load_direction_i)
            2'b00: mem <= mem;
            2'b01: mem <= vertical_i;
            2'b10: mem <= diagonal_i;
            default: mem <= horizontal_i;
        endcase
    end
end
    
endmodule