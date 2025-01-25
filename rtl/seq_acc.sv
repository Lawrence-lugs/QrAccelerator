/* 

n-Bit input MAC accelerator
uses n cycles to complete an n-bit input mac

*/

import qracc_pkg::*;

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

    // Passthrough signals
    output to_analog_t to_analog,
    input from_analog_t from_analog_i
);

// Parameters
localparam accumulatorBits = $clog2(inputBits) + adcBits + 1; // +1 from addition bit growth
localparam pipelineStages = inputBits + 2;

// Signals
logic [pipelineStages-1:0] pipeline_tracker;
logic [inputElements-1:0][inputBits-1:0] piso_buffer_q;
logic [outputElements-1:0][outputBits-1:0] mac_data_o;
logic [outputElements-1:0][accumulatorBits-1:0] accumulator;
logic doiroundup;

// Modules
qr_acc_wrapper #(
    .numRows(numRows),
    .numCols(numCols),
    .numAdcBits(numAdcBits),
    .numCfgBits(numCfgBits)
) u_qr_acc_wrapper (
    .clk(clk),
    .nrst(nrst),
    // CONFIG
    .n_input_bits_cfg(n_input_bits_cfg),
    .n_adc_bits_cfg(n_adc_bits_cfg),
    .binary_cfg(mode_cfg),
    
    .to_analog_o(to_analog),
    .from_analog_i(from_analog),

    // DIGITAL INTERFACE: MAC
    .adc_out_o(adc_out),
    .mac_en_i(mac_en),
    .data_p_i(data_p_i),
    .data_n_i(data_n_i),
    // DIGITAL INTERFACE: SRAM
    .rq_wr_i(rq_wr),
    .rq_valid_i(rq_valid),
    .rq_ready_o(rq_ready),
    .rd_valid_o(rd_valid),
    .rd_data_o(rd_data),
    .wr_data_i(wr_data),
    .addr_i(addr)
);

twos_to_bipolar #(
    .inBits(2),
    .numLanes(numRows)
) u_twos_to_bipolar (
    .twos(x_data),
    .bipolar_p(data_p_i),
    .bipolar_n(data_n_i)
);

// Registers
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

// Datapaths
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