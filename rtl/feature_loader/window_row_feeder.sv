// Aligned Feature Loader Element
// Technically a SIPO

module window_row_feeder #(
    parameter elementWidth  = 4,
    // Don't touch for now
    parameter kernelWidth = 3     
) (
    input clk, nrst,
    input [elementWidth-1:0]                    feature_serial_i,
    output [kernelWidth-1:0][elementWidth-1:0]  feature_o,
    input load_i
);

    logic [kernelWidth-1:0][elementWidth-1:0] sipo;
    logic [elementWidth-1:0] feature_serial;

    always_ff @( posedge clk or negedge nrst ) begin : sipoReg
        if (!nrst) begin
            sipo <= 0;
        end else begin 
            if (load_i) begin
                for (int i = 0; i < kernelWidth-1; i++) begin
                    sipo[i+1] <= sipo[i];
                end
                sipo[0] <= feature_serial_i;
            end
        end
    end 

    assign feature_o = sipo;

endmodule