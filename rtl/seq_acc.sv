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
    // ADC half-span in counts at adc_ref_range_shifts == 0 (power of two).
    parameter int adcFullScale = (1 << adcBits),
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
// The bipolar bias is weight-independent: one value for the whole window.
logic signed [accumulatorBits-1:0] bias_out;
// Activation popcount delayed one cycle, i.e. captured on the same edge as
// the ADC register: it then corresponds to the same activation bit as
// tree_sum.  (Signed: positive lanes minus negative lanes.)
logic signed [31:0] act_popcount_q;
logic signed [accumulatorBits+16:0] bias_corrected;
logic signed [accumulatorBits+16:0] scaled_acc;
int lsb_exp;
logic mac_en;
logic [3:0] input_bits;
logic [3:0] input_trits;
logic [4:0] input_bits_raw;

// If the activations are unsigned, the effective bits is +1
assign input_bits_raw = cfg.n_input_bits_cfg + {1'b0,cfg.unsigned_acts};
assign input_bits = (input_bits_raw > maxInputBits) ? maxInputBits[3:0] : input_bits_raw;
// Unsigned activations are magnitudes: all n_input_bits are data bits.  For
// signed/ternary inputs the top bit is the sign, so only n-1 are trits.
assign input_trits = cfg.unsigned_acts
    ? ((cfg.n_input_bits_cfg > maxInputBits) ? maxInputBits[3:0]
                                             : cfg.n_input_bits_cfg)
    : ((cfg.n_input_bits_cfg > maxInputBits) ? maxInputBits[3:0] - 1'b1
                                             : cfg.n_input_bits_cfg - 1'b1);

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
            .numAdcBits(adcBits)
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
    .input_bits(input_bits),
    .unsigned_acts(cfg.unsigned_acts)
);

// Bipolar switch matrix: mbl = 2P - A_j, so the accumulator holds
// 2*MAC + sum_j 2**j A_j.  Remove the weight-independent bias in lock-step
// with the MAC shift-add.  `act_popcount_q` is delayed by one cycle, exactly
// like the ADC register, so it lines up with tree_sum.
wire mac_accept = mac_valid_i && ready_o;
bipolar_bias_sub #(
    .maxInputTrits(maxInputBits),
    .accumulatorBits(accumulatorBits)
) u_bipolar_bias_sub (
    .clk(clk),
    .nrst(nrst),
    // The bias removal assumes two's-complement weight planes, where
    // sum_b sign_b*2**b == -1.  Legacy unsigned 1-bit planes use a different
    // convention (and the existing seq_acc tests depend on it), and binary
    // mode does not create the 2P-A column current at all.
    .bias_enable(!cfg.binary_cfg && cfg.weight_signed_cfg),
    .input_trits_i(input_trits),
    .mac_valid(mac_accept),
    .popcount_i(act_popcount_q),
    .valid_o(),
    .bias_o(bias_out)
);

// Registers
always_ff @( posedge clk ) begin : seqAccRegs

    // Activation popcount, delayed one cycle to match the ADC register.
    if (!nrst) begin
        act_popcount_q <= '0;
    end else begin
        act_popcount_q <= $countones(data_p_i) - $countones(data_n_i);
    end

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

    // Ready mask looks for workload in the first input_trits stages.  The
    // final stage must be included: accepting while the previous word is still
    // at bit T-1 puts the new word's first shift-add at the same edge as the
    // previous word's last one (seen for T=8 unsigned activations), which
    // dropped the last partial and corrupted the bias.
    ready_mask = 2**input_trits - 1;
    // MAC enable looks for workload in the first input_trits stages
    mac_en_mask = 2**input_trits - 1;
    // Valid mask looks for workload in the last stage
    valid_mask = 2**(input_trits+1);

    // If something is in the first input_trits-1 stages of the pipeline we cannot take new data (ready_o asserted in the last cycle that PISOs are needed)
    ready_o = (pipeline_tracker & ready_mask) == '0;
    valid_o = (pipeline_tracker & valid_mask) != '0;
    // If something is in the first input_trits stages of the pipeline, we need to enable the MAC
    mac_en = (pipeline_tracker & mac_en_mask) != '0; 

    // lsb = adcFullScale / 2**(adcBits-1+s), an exact power of two.
    lsb_exp = $clog2(adcFullScale) - (adcBits - 1)
              - int'(cfg.adc_ref_range_shifts);

    for (int i = 0; i < outputElements; i++) begin
        if (adcBits > 4 || (!cfg.binary_cfg && cfg.weight_signed_cfg)) begin
            // Corrected path: acc holds mbl/lsb in code units, so
            //   MAC = (lsb*acc - sum_j 2**j A_j) / 2
            // and seq_acc publishes 2*MAC (the factor 2 is absorbed by the
            // output scaler).  For adcBits > 4 this also applies to the
            // unipolar/binary model (with bias == 0).
            // The 4-bit legacy configurations keep the historical
            // `acc << s` scaling below.
            scaled_acc = $signed(accumulator[i]);
            if (lsb_exp >= 0)
                scaled_acc = scaled_acc <<< lsb_exp;
            else
                scaled_acc = scaled_acc >>> (-lsb_exp);
            bias_corrected = scaled_acc - $signed(bias_out);
            mac_data_o[i] = bias_corrected <<< cfg.adc_ref_range_shifts;
        end else begin
            // Legacy unsigned 1-bit path and binary mode: unchanged.
            mac_data_o[i] = accumulator[i] << cfg.adc_ref_range_shifts;
        end
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
        $display("[DBG seq_acc] pre_shift n=%0d i=%0d accumulator[%0d]=%0d bias[%0d]=%0d mac_data_o[%0d]=%0h",
                 dbg_pre_shift_cnt, i, i, $signed(accumulator[i]), i,
                 $signed(bias_out), i, mac_data_o[i]);
    end
end
`endif

endmodule