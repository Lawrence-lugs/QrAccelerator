// Aligned Feature Loader (from UNPU)
// "Memory with weird shifting"

module aligned_feature_loader #(
    parameter aflDimY       = 128   ,
    parameter aflDimX       = 6    ,
    parameter inputWidth    = 32    ,
    parameter elementWidth  = 4     ,
    parameter addrWidth     = 32    , // Minimum $clog2(aflDimY/inputElements)
    localparam inputElements = inputWidth/elementWidth
) (
    input clk, nrst,

    // Input Interface
    input logic [inputWidth-1:0]    data_i  ,
    input logic [addrWidth-1:0]     input_addr_offset,
    input logic                     valid_i ,

    // Output Interface
    output logic [aflDimY-1:0][elementWidth-1:0] data_o,

    // Control
    // TODO : What's the consequences of broadcasting this?
    input logic [aflDimX-1:0][aflDimY-1:0][1:0] ctrl_load_direction_i 
);

// Signals
logic [elementWidth-1:0] feature_pass [aflDimX][aflDimY];

// Module
generate
    for(genvar x = 0; x < aflDimX; x++) begin
        for(genvar y = 0; y < aflDimY; y++) begin
            afl_element #(
                .elementWidth(elementWidth)
            ) u_afl_element (
                .clk                (clk),
                .nrst               (nrst),
                .horizontal_i       (feature_pass[x-1][y]),
                .diagonal_i         (feature_pass[x-1][y-1]),
                .vertical_i         (feature_pass[x][y-1]),
                .feature_o          (feature_pass[x][y]),
                .load_direction_i   (ctrl_load_direction_i[x][y])
            );
        end
    end
endgenerate

endmodule