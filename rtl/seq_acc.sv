/* 

n-Bit input MAC accelerator
uses n cycles to complete an n-bit input mac
asdasd
*/

import qracc_pkg::*;

module seq_acc #(
    parameter inputBits = 5,
    parameter inputElements = 128,
    parameter outputElements = 32,
    parameter adcBits = 4,
    localparam inputTrits = inputBits - 1,
    // localparam accumulatorBits = inputTrits  + adcBits + 1 // +1 from addition bit growth
    localparam accumulatorBits = 16
) (
    input clk, nrst,

    input qracc_config_t cfg,

    // Data
    input [inputElements-1:0][inputBits-1:0] mac_data_i,
    input mac_valid_i,
    output logic ready_o,
    output logic valid_o,
    output logic [outputElements-1:0][accumulatorBits-1:0] mac_data_o,

    // Passthrough signals
    output to_analog_t to_analog_o,
    input from_analog_t from_analog_i,
    
    output from_sram_t from_sram,
    input to_sram_t to_sram
);

// Parameters
localparam pipelineStages = inputTrits + 2;

// Signals
logic [pipelineStages-1:0] pipeline_tracker;
logic signed [inputElements-1:0][inputTrits-1:0] piso_buffer_n_q;
logic signed [inputElements-1:0][inputTrits-1:0] piso_buffer_p_q;
logic signed [inputElements-1:0][inputTrits-1:0] piso_buffer_n_d;
logic signed [inputElements-1:0][inputTrits-1:0] piso_buffer_p_d;
logic [outputElements-1:0][accumulatorBits-1:0] accumulator;
logic [inputElements-1:0] data_p_i;
logic [inputElements-1:0] data_n_i;
logic [outputElements-1:0][adcBits-1:0] adc_out;
logic mac_en;

// Modules
qr_acc_wrapper #(
    .numRows(inputElements),
    .numCols(outputElements),
    .numAdcBits(numAdcBits),
    .numCfgBits(numCfgBits)
) u_qr_acc_wrapper (
    .clk(clk),
    .nrst(nrst),
    // CONFIG
    .cfg(cfg),
    
    // ANALOG
    .to_analog_o(to_analog_o),
    .from_analog_i(from_analog_i),

    // DIGITAL INTERFACE: MAC
    .adc_out_o(adc_out),
    .mac_en_i(mac_en),
    .data_p_i(data_p_i),
    .data_n_i(data_n_i),

    // DIGITAL INTERFACE: SRAM
    .from_sram(from_sram),
    .to_sram(to_sram)
);

twos_to_bipolar #(
    .inBits(inputBits),
    .numLanes(inputElements)
) u_twos_to_bipolar (
    .twos(mac_data_i),
    .bipolar_p(piso_buffer_p_d),
    .bipolar_n(piso_buffer_n_d)
);

// Registers
always_ff @( posedge clk ) begin : seqAccRegs

    // PISO Buffer
    if (!nrst) begin
        piso_buffer_n_q <= '0;
        piso_buffer_p_q <= '0;
    end else begin
        if (mac_valid_i && ready_o) begin
            piso_buffer_n_q <= piso_buffer_n_d;
            piso_buffer_p_q <= piso_buffer_p_d;
        end else begin
            for (int i = 0; i < inputElements; i++) begin
                piso_buffer_n_q[i] <= piso_buffer_n_q[i] >> 1;
                piso_buffer_p_q[i] <= piso_buffer_p_q[i] >> 1;
            end
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
        for (int i = 0; i < outputElements; i++) begin
            if (pipeline_tracker[1]) begin // == 'h02
                accumulator[i] <= accumulatorBits'(signed'(adc_out[i])) << (inputTrits - 1); 
            end else begin
                accumulator[i] <= {accumulator[i][accumulatorBits-1],accumulator[i][accumulatorBits-1:1]} + ( accumulatorBits'(signed'(adc_out[i])) << (inputTrits - 1) );
            end
        end
    end
end

// Datapaths

always_comb begin : seqAccDpath
    // If something is in the first 3 stages of the pipeline we cannot take new data
    ready_o = (pipeline_tracker[inputTrits-2:0] == 3'b000);
    valid_o = pipeline_tracker[pipelineStages-1];
    mac_en = (pipeline_tracker[inputTrits-1:0] != 4'b0000); 

    for (int i = 0; i < outputElements; i++) begin
        mac_data_o[i] = accumulator[i] << cfg.adc_ref_range_shifts;
    end

    // Data input
    for (int i = 0; i < inputElements; i++) begin
        data_p_i[i] = piso_buffer_p_q[i][0];
        data_n_i[i] = piso_buffer_n_q[i][0];
    end
end

endmodule