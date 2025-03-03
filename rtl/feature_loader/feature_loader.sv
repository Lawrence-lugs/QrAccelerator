// Aligned Feature Loader (from UNPU)

module feature_loader #(
    parameter aflDimY       = 128   ,
    parameter aflDimX       = 32    ,
    parameter inputWidth    = 32    ,
    parameter elementWidth  = 4     ,
    // No touch
    parameter kernelWidth   = 3     ,
    localparam inputElements = inputWidth/elementWidth,
    localparam numFeeders = aflDimY/kernelWidth
) (
    // Input Interface
    input logic [inputWidth-1:0]    data_i  ,
    input logic [numFeeders-1:0]    feeder_offset,
    input logic                     valid_i ,

    // Output Interface
    output logic [aflDimY-1:0][elementWidth-1:0] data_o
);

// numFeeders*elementWidth > inputWidth
// However, the alignment can be handled by shifting with a control offset
logic [numFeeders-1:0][elementWidth-1:0] feeder_serial_inputs;

// Slice and align input data to offset
always_comb begin : dataSlicingOffset
    feeder_serial_inputs = data_i << (feeder_offset * elementWidth);
end

// Module : window_row_feeder
generate
    for(genvar i = 0; i < aflDimY; i++) begin
        window_row_feeder u_wf(
            .clk(clk),
            .nrst(nrst),
            .feature_serial_i(feeder_serial_inputs[i]),
            .feature_o(data_o[i]),
            .load_i(valid_i)
        );
    end
endgenerate
    
endmodule