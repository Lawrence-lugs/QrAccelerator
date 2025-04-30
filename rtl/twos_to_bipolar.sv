// Twos complement to bipolar converter
// 
// Output bits require inBits if unsigned, or inBits-1 if signed
// 

module twos_to_bipolar #(
    parameter inBits = 8,
    parameter numLanes = 1
) (
    input signed [numLanes-1:0][inBits-1:0] twos,
    input [3:0] input_bits,
    output logic [numLanes-1:0][inBits-1:0] bipolar_p,
    output logic [numLanes-1:0][inBits-1:0] bipolar_n
);

logic signed [numLanes-1:0][inBits-1:0] ntwos;
always_comb begin : dataPath
    for (int i = 0; i < numLanes; i++) begin    
        ntwos[i] = -twos[i];
        if (twos[i] == 0) begin
            bipolar_p[i] = 0;
            bipolar_n[i] = 0;
        end
        else begin
            if (twos[i][input_bits-1]) begin
                bipolar_p[i] = '0;
                bipolar_n[i] = ntwos[i];
            end else begin
                bipolar_p[i] = twos[i];
                bipolar_n[i] = '0;
            end
        end
    end
end

endmodule