/* 

n-Bit input MAC accelerator
uses n cycles to complete an n-bit input mac
asdasd
*/
`timescale 1ns/1ps

import qracc_pkg::*;

module seq_acc #(
    parameter maxInputBits = qrAccMaxInputBits,
    parameter inputElements = 128,
    parameter outputElements = 32,
    
    parameter numCols = 32,
    parameter int numPlanes = 8,
    parameter int numBeatRows = 4,

    parameter adcBits = 4,
    parameter accumulatorBits = 16
    // localparam accumulatorBits = maxInputTrits  + adcBits + 1 // +1 from addition bit growth
) (
    input clk, nrst,

    input qracc_config_t cfg,

    // Data
    input [inputElements-1:0][maxInputBits-1:0] mac_data_i,
    input mac_valid_i,
    output logic ready_o,

    // Valid but no ready because we cannot stall
    output logic valid_o,
    output logic [outputElements-1:0][accumulatorBits-1:0] mac_data_o,

    // Passthrough signals
    output to_analog_t to_analog_o [numPlanes-1:0],
    input from_analog_t from_analog_i [numPlanes-1:0],
    
    // SRAM signals
    input to_sram_rq_wr,
    input to_sram_rq_valid,
    input [1:0] wr_bus_sel_i,
    input [numBeatRows*numPlanes*numCols-1:0] to_sram_wr_data,
    input [$clog2(numRows)-1:0] to_sram_addr,
    output logic from_sram_rq_ready,
    output logic from_sram_rd_valid,
    output logic [numCols-1:0] from_sram_rd_data
);

// Parameters
localparam pipelineStages = maxInputBits + 2;

// Signals
logic [pipelineStages-1:0] pipeline_tracker;
logic signed [inputElements-1:0][maxInputBits-1:0] piso_buffer_n_q;
logic signed [inputElements-1:0][maxInputBits-1:0] piso_buffer_p_q;
logic signed [inputElements-1:0][maxInputBits-1:0] piso_buffer_n_d;
logic signed [inputElements-1:0][maxInputBits-1:0] piso_buffer_p_d;
logic [outputElements-1:0][accumulatorBits-1:0] accumulator;
logic [inputElements-1:0] data_p_i;
logic [inputElements-1:0] data_n_i;
logic signed [numPlanes-1:0][outputElements-1:0][adcBits-1:0] plane_adc_out;
logic signed [outputElements-1:0][adcBits+numPlanes-1:0] tree_sum;
logic mac_en;
logic [3:0] input_bits;
logic [3:0] input_trits;
logic [4:0] input_bits_raw;

// If the activations are unsigned, the effective bits is +1
assign input_bits_raw = cfg.n_input_bits_cfg + {1'b0,cfg.unsigned_acts};
assign input_bits = (input_bits_raw > maxInputBits) ? maxInputBits[3:0] : input_bits_raw;
assign input_trits = input_bits - 1;

// Modules
genvar planeIdx;
generate
    for (planeIdx = 0; planeIdx < numPlanes; planeIdx++) begin : g_plane
        logic [numBeatRows*numCols-1:0] planeWr;

        always_comb begin
            for (int r = 0; r < numBeatRows; r++) begin
                planeWr[r*numCols +: numCols] = to_sram_wr_data[r*numPlanes*numCols + planeIdx*numCols +: numCols];
            end
        end

        qr_acc_wrapper #(
            .numRows(inputElements),
            .numCols(numCols),
            .outputElements(outputElements),
            .numAdcBits(numAdcBits)
        ) u_qr_acc_wrapper (
            .clk(clk),
            .nrst(nrst),
            // CONFIG
            .cfg(cfg),
            
            // ANALOG
            .to_analog_o(to_analog_o[planeIdx]),
            .from_analog_i(from_analog_i[planeIdx]),

            // DIGITAL INTERFACE: MAC
            .adc_out_o(plane_adc_out[planeIdx]),
            .mac_en_i(mac_en),
            .data_p_i(data_p_i),
            .data_n_i(data_n_i),

            // DIGITAL INTERFACE: SRAM
            .wr_bus_sel_i               (wr_bus_sel_i),
            .to_sram_rq_wr              (to_sram_rq_wr),
            .to_sram_rq_valid           (to_sram_rq_valid),
            .to_sram_wr_data            (planeWr),
            .to_sram_addr               (to_sram_addr),
            .from_sram_rq_ready         (from_sram_rq_ready_plane[planeIdx]),
            .from_sram_rd_valid         (from_sram_rd_valid_plane[planeIdx]),
            .from_sram_rd_data          (from_sram_rd_data_plane[planeIdx])
        );
    end
endgenerate

logic [numPlanes-1:0] from_sram_rq_ready_plane;
logic [numPlanes-1:0] from_sram_rd_valid_plane;
logic [numPlanes-1:0][numCols-1:0] from_sram_rd_data_plane;

assign from_sram_rq_ready = |from_sram_rq_ready_plane;
assign from_sram_rd_valid = |from_sram_rd_valid_plane;

always_comb begin
    from_sram_rd_data = '0;
    for (int p = 0; p < numPlanes; p++) begin
        from_sram_rd_data |= from_sram_rd_data_plane[p];
    end
end

shift_add_tree #(
    .numPlanes(numPlanes),
    .numOutputs(outputElements),
    .partialBits(adcBits)
) u_shift_add_tree (
    .weight_bits_i(cfg.weight_bits_cfg),
    .weight_signed_i(cfg.weight_signed_cfg),
    .partial_i(plane_adc_out),
    .sum_o(tree_sum)
);

twos_to_bipolar #(
    .inBits(maxInputBits),
    .numLanes(inputElements)
) u_twos_to_bipolar (
    .twos(mac_data_i),
    .bipolar_p(piso_buffer_p_d),
    .bipolar_n(piso_buffer_n_d),
    .input_bits(input_bits)
);

// Registers
always_ff @( posedge clk ) begin : seqAccRegs

    // PISO Buffer
    if (!nrst) begin
        piso_buffer_n_q <= '0;
        piso_buffer_p_q <= '0;
    end else begin
        if (mac_valid_i && ready_o) begin
            `ifdef TRACK_STATISTICS
            stats.statSeqAccOperations++;
            `endif
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
        // Left shift
        pipeline_tracker[pipelineStages-1:1] <= pipeline_tracker[pipelineStages-2:0];
    end

    // Accumulator
    if (!nrst) begin
        accumulator <= '0;
    end else begin
        for (int i = 0; i < outputElements; i++) begin
            if (pipeline_tracker[1]) begin // == 'h02
                accumulator[i] <= accumulatorBits'(signed'(tree_sum[i])) << (input_trits - 1); // bit 0 result
            end else begin
                accumulator[i] <= {accumulator[i][accumulatorBits-1],accumulator[i][accumulatorBits-1:1]} + ( accumulatorBits'(signed'(tree_sum[i])) << (input_trits - 1) );
            end
        end
    end
end

// Datapaths
logic [pipelineStages-1:0] ready_mask;
logic [pipelineStages-1:0] valid_mask;
logic [pipelineStages-1:0] mac_en_mask;

always_comb begin : seqAccDpath

    // Ready mask looks for workload in the first input_trits-1 stages
    ready_mask = 2**(input_trits-1) - 1;
    // MAC enable looks for workload in the first input_trits stages
    mac_en_mask = 2**input_trits - 1;
    // Valid mask looks for workload in the last stage
    valid_mask = 2**(input_trits+1);

    // If something is in the first input_trits-1 stages of the pipeline we cannot take new data (ready_o asserted in the last cycle that PISOs are needed)
    ready_o = (pipeline_tracker & ready_mask) == '0;
    valid_o = (pipeline_tracker & valid_mask) != '0;
    // If something is in the first input_trits stages of the pipeline, we need to enable the MAC
    mac_en = (pipeline_tracker & mac_en_mask) != '0; 

    for (int i = 0; i < outputElements; i++) begin
        mac_data_o[i] = accumulator[i] << cfg.adc_ref_range_shifts;
    end

    // Data input
    for (int i = 0; i < inputElements; i++) begin
        data_p_i[i] = piso_buffer_p_q[i][0];
        data_n_i[i] = piso_buffer_n_q[i][0];
    end
end

`ifdef DEBUG
int dbg_ev;
int dbg_nz;
int dbg_first;
initial dbg_ev = 0;
always @(posedge clk) begin
  if (mac_valid_i && ready_o && dbg_ev < 2) begin
    dbg_nz = 0;
    dbg_first = -1;
    for (int i = 0; i < inputElements; i++) begin
      if (mac_data_i[i] != 0) begin
        dbg_nz = dbg_nz + 1;
        if (dbg_first < 0) dbg_first = i;
      end
    end
    if (dbg_nz > 0) begin
      $display("[DBG seq_acc] event=%0d nz_lanes=%0d first_lane=%0d", dbg_ev, dbg_nz, dbg_first);
      for (int i = 0; i < inputElements; i++)
        $display("[DBG seq_acc] event=%0d act[%0d]=%0d", dbg_ev, i, mac_data_i[i]);
      for (int p = 0; p < numPlanes; p++)
        $display("[DBG seq_acc] event=%0d plane=%0d adc_out[0]=%0d", dbg_ev, p, $signed(plane_adc_out[p][0]));
      $display("[DBG seq_acc] event=%0d tree_sum[0]=%0d", dbg_ev, $signed(tree_sum[0]));
      dbg_ev = dbg_ev + 1;
    end
  end
end
`endif

`ifdef DEBUG
int dbg_out_cnt = 0;
always_ff @(posedge clk) if (valid_o && dbg_out_cnt < 2) begin
    dbg_out_cnt <= dbg_out_cnt + 1;
    $display("[DBG seq_acc] out n=%0d mac_data_o[0]=%0h mac_data_o[1]=%0h mac_data_o[2]=%0h mac_data_o[3]=%0h accumulator[0]=%0d", dbg_out_cnt, mac_data_o[0], mac_data_o[1], mac_data_o[2], mac_data_o[3], $signed(accumulator[0]));
end
`endif

`ifdef DEBUG
int dbg_pre_shift_cnt = 0;
always_ff @(posedge clk) if (valid_o && dbg_pre_shift_cnt < 2) begin
    dbg_pre_shift_cnt <= dbg_pre_shift_cnt + 1;
    for (int i = 0; i < outputElements; i++) begin
        $display("[DBG seq_acc] pre_shift n=%0d i=%0d accumulator[%0d]=%0d mac_data_o[%0d]=%0h",
                 dbg_pre_shift_cnt, i, i, $signed(accumulator[i]), i, mac_data_o[i]);
    end
end
`endif

endmodule