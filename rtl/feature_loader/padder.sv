
// Combinational block that pads passing data to a specific value

`timescale 1ns/1ps

module padder #(
    parameter elementWidth = 8,
    parameter numElements = 32
) (
    input [numElements-1:0][elementWidth-1:0] data_i,

    input [15:0] pad_start,
    input [15:0] pad_end,

    input [elementWidth-1:0] pad_value,

    output logic [numElements-1:0][elementWidth-1:0] data_o
);

logic [15:0] pad_low_limit;
logic [15:0] pad_high_limit;
    
always_comb begin : padDecode
    pad_low_limit = numElements > $signed(pad_end) ? numElements - pad_end : 0;
    pad_high_limit = numElements > $signed(pad_start) ? numElements - pad_start : 0;
    for (int i = 0; i < numElements; i++) begin
        // We pad from the end due to the endianness of the data from actmem
        if (i >= pad_low_limit && i < pad_high_limit) begin
            data_o[i] = pad_value;
        end else begin
            data_o[i] = data_i[i];
        end
    end
end

endmodule