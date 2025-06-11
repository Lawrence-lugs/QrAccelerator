
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
    
always_comb begin : padDecode
    for (int i = 0; i < numElements; i++) begin
        // We pad from the end due to the endianness of the data from actmem
        if (i >= (numElements-pad_end) && i < (numElements-pad_start)) begin
            data_o[i] = pad_value;
        end else begin
            data_o[i] = data_i[i];
        end
    end
end

endmodule