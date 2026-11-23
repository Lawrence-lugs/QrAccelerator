// Bipolar switch-matrix bias removal.
//
// In bipolar mode the column current is
//
//     mbl_value = 2*P - A_j
//
// where P is the per-plane partial product and A_j is the number of lanes whose
// activation bit j is set.  The seq_acc shift-add therefore accumulates
//
//     accumulator = 2*MAC + sum_j 2**j A_j
//
// This block accumulates that weight-independent bias term in lock-step with
// the MAC (same shift/add recurrence, same pipeline timing) so seq_acc can
// subtract it before the output shift:
//
//     MAC = (accumulator - bias) / 2
//
// The residual factor 2 is absorbed by the output scaler (see output_scaler).
// In binary mode (binary_cfg == 1) the block holds bias_o at zero.
//
// Timing: `mac_valid` is seq_acc's accept condition (mac_valid_i && ready_o),
// i.e. the same signal that sets pipeline_tracker[0].  `popcount_i` is the
// number of active lanes of the *previous* cycle's data_p vector, i.e. it has
// been delayed by one cycle exactly like the ADC register.  See seq_acc.sv.
module bipolar_bias_sub #(
    // Deepest supported activation width (runtime cfg may be narrower).
    parameter int maxInputTrits = 8,
    parameter int accumulatorBits = 16
) (
    input  logic                            clk,
    input  logic                            nrst,
    input  logic                            bias_enable,
    input  logic [3:0]                      input_trits_i,
    input  logic                            mac_valid,
    input  logic signed [31:0]              popcount_i,
    output logic                            valid_o,
    output logic signed [accumulatorBits-1:0] bias_o
);

    localparam int pipelineStages = maxInputTrits + 2;

    logic [pipelineStages-1:0] tracker;
    logic first;
    logic active;
    logic last;

    // Same stage masks as seq_acc: first partial at bit 1, last at bit T.
    // T is a runtime CSR field, so these are variable shifts/masks.
    assign first  = tracker[1];
    assign last   = tracker[input_trits_i];
    assign active = |(tracker & ((1 << (input_trits_i + 1)) - 2));

    always_ff @(posedge clk) begin : biasAccumulator
        if (!nrst) begin
            tracker <= '0;
            valid_o <= 1'b0;
            bias_o  <= '0;
        end else begin
            tracker[0] <= mac_valid;
            tracker[pipelineStages-1:1] <= tracker[pipelineStages-2:0];

            // `last` is the final shift-add stage; seq_acc asserts valid_o in
            // the following cycle (pipeline_tracker[T+1]).
            valid_o <= last;

            if (!bias_enable) begin
                bias_o <= '0;
            end else if (first) begin
                bias_o <= accumulatorBits'(popcount_i) << (input_trits_i - 1);
            end else if (active) begin
                bias_o <= (bias_o >>> 1)
                          + (accumulatorBits'(popcount_i) << (input_trits_i - 1));
            end else begin
                bias_o <= bias_o >>> 1;
            end
        end
    end

endmodule
