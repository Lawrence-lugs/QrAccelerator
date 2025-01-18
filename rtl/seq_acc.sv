/* 

n-Bit input MAC accelerator
uses n cycles to complete an n-bit input mac

*/

module seq_acc #(
    parameter inputBits = 4,
    parameter inputElements = 128,
    parameter outputBits = 4,
    parameter outputElements = 32,
    parameter adcBits = 4
) (
    input clk, nrst,

    // Data inputs
    input [inputElements-1:0][inputBits-1:0] mac_data_i,
    input [inputElements-1:0] mac_valid_i,
    output logic ready_o,
    
    output logic valid_o,
    output logic [outputElements-1:0][outputBits-1:0] mac_data_o,

    input [outputElements-1:0][adcBits-1:0] adc_i

);

localparam accumulatorBits = $clog2(inputBits) + adcBits + 1; // +1 from addition bit growth
localparam pipelineStages = inputBits + 2;

logic [pipelineStages-1:0] pipeline_tracker;
logic [inputElements-1:0][inputBits-1:0] piso_buffer_q;
logic [outputElements-1:0][outputBits-1:0] mac_data_o;
logic [outputElements-1:0][accumulatorBits-1:0] accumulator;
logic doiroundup;

always_ff @( posedge clk ) begin : seqAccRegs
    // State reg
    if(!nrst) state_q <= S_IDLE;
    else state_q <= state_d;

    // PISO Buffer
    if (!nrst) begin
        piso_buffer_q <= '0;
    end else begin
        if (mac_valid_i && ready_o) begin
            piso_buffer_q <= mac_data_i;
        end else begin
            // We need the sign bit preserved
            piso_buffer_q <= piso_buffer_q >>> 1;
        end
    end

    // Pipeline tracker
    if (!nrst) begin
        pipeline_tracker <= '0;
    end else begin
        if (mac_valid_i && ready_o) begin
            pipeline_tracker[0] <= '1;
        end else begin
            pipeline_tracker[0] <= '0;
        end
        // I wonder if there's a more readable way to shift this
        // Left shift
        pipeline_tracker[pipelineStages-1:1] <= pipeline_tracker[pipelineStages-2:0];
    end

    // Accumulator
    if (!nrst) begin
        accumulator <= '0;
    end else begin
        if (mac_valid_i && ready_o) begin
            for (int i = 0; i < outputElements; i++) begin
                accumulator[i] <= (accumulator[i] <<< 1) + accumulatorBits'(signed'(adc_i[i]));
            end
        end
    end
end

always_comb begin : seqAccDpath
    // If something is in the first 3 stages of the pipeline
    // We cannot take in new data
    ready_o = (pipeline_tracker[pipelineStage-3:0] != 3'b000)
    valid_o = pipeline_tracker[pipelineStages-1];

    // Rounding adds a teeny tiny adder to the output delay.
    // Could be pipelined again, but that may be overengineering
    doiroundup = accumulatorBits[accumulatorBits-outputBits-1:0] != 0;
    for (int i = 0; i < outputElements; i++) begin
        mac_data_o[i] = accumulator[i][accumulatorBits-1 -: outputBits] + doiroundup;
    end
end

    
endmodule