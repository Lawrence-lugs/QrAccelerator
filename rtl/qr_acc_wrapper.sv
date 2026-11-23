
// Wraps the analog QR accelerator.
// Performs a 1-bit bipolar MAC operation with parametrizable output precision.
//
// TIMING / ANALOG CO-SIMULATION NOTE (2026-11-18): the switch-matrix selects are
// driven from data_p/data_n for the whole MAC word and are blanked only when
// !mac_en_i.  The previous `clk && mac_en_i` blanking only drove data during
// the low phase; any analog/VAMS testbench that sampled the column on a
// particular clock phase must be re-timed and re-verified against this model.

import qracc_pkg::*;

module qr_acc_wrapper #(
    parameter numRows = 128,
    parameter outputElements = 128,
    parameter numCols = 32,
    parameter numAdcBits = 4,
    parameter int numBeatRows = 4,
    parameter compCount = (2**numAdcBits)-1 // An ADC only has 2^numAdcBits-1 comparators
) ( 
    input clk,
    input nrst,

    // CONFIG
    input qracc_config_t cfg,

    input from_analog_t from_analog_i,
    output to_analog_t to_analog_o,

    // DIGITAL INTERFACE: MAC
    output logic [outputElements-1:0][numAdcBits-1:0] adc_out_o,
    input mac_en_i,
    input [numRows-1:0] data_p_i,
    input [numRows-1:0] data_n_i,
    
    // SRAM signals
    input to_sram_rq_wr,
    input to_sram_rq_valid,
    input [1:0] wr_bus_sel_i,
    input [numBeatRows*numCols-1:0] to_sram_wr_data,
    input [$clog2(numRows)-1:0] to_sram_addr,
    output logic from_sram_rq_ready,
    output logic from_sram_rd_valid,
    output logic [numCols-1:0] from_sram_rd_data
);

logic wc_write;
logic wc_read;
logic wc_done;
logic [outputElements-1:0][numAdcBits-1:0] adc_out_encoded;
logic [outputElements-1:0][compCount-1:0] adc_out;

// ADC OUT -- realign flattened ADC output.  The synthesised interface is the
// 4-bit thermometer bus; wider behavioural converters (the bit-exact seq_acc
// tests use 12 bits) use the digital ADC_CODE tap instead.
generate
    if (numAdcBits == 4) begin : g_adc_thermometer
        assign adc_out = from_analog_i.ADC_OUT;
    end
endgenerate

// SWITCH MATRIX SELECTS
always_comb begin : SwitchMatrixSelects
    if (cfg.binary_cfg) begin
        // Binary configuration
        // Drive the column for the whole MAC word and blank only BETWEEN words.
        // Gating on clk as well used to force every select to VRST on the
        // posedge, i.e. exactly when the ADC register samples: the digital
        // datapath always saw mbl_value == 0 (FINDINGS §1).
        if (!mac_en_i) begin
            to_analog_o.PSM_VDR_SEL = 0;
            to_analog_o.PSM_VSS_SEL = 0;
            to_analog_o.PSM_VRST_SEL = '1; // '1 = all ones
        end else begin
            to_analog_o.PSM_VDR_SEL = data_p_i & ~data_n_i;
            to_analog_o.PSM_VSS_SEL = data_n_i & ~data_p_i;
            to_analog_o.PSM_VRST_SEL = ~data_p_i & ~data_n_i;
        end
        to_analog_o.PSM_VDR_SELB = ~to_analog_o.PSM_VDR_SEL;
        to_analog_o.PSM_VSS_SELB = ~to_analog_o.PSM_VSS_SEL;
        to_analog_o.PSM_VRST_SELB = ~to_analog_o.PSM_VRST_SEL;

        // In binary config, the NSM always points to VRST
        to_analog_o.NSM_VDR_SEL = 0;
        to_analog_o.NSM_VSS_SEL = 0;
        to_analog_o.NSM_VRST_SEL = '1; // '1 = all ones
        to_analog_o.NSM_VDR_SELB = ~to_analog_o.NSM_VDR_SEL;
        to_analog_o.NSM_VSS_SELB = ~to_analog_o.NSM_VSS_SEL;
        to_analog_o.NSM_VRST_SELB = ~to_analog_o.NSM_VRST_SEL;
        
    end else begin
        // Bipolar configuration
        if (!mac_en_i) begin
            to_analog_o.PSM_VDR_SEL = 0;
            to_analog_o.PSM_VSS_SEL = 0;
            to_analog_o.PSM_VRST_SEL = '1; // '1 = all ones
        end else begin
            to_analog_o.PSM_VDR_SEL = data_p_i & ~data_n_i;
            to_analog_o.PSM_VSS_SEL = data_n_i & ~data_p_i;
            to_analog_o.PSM_VRST_SEL = ~data_p_i & ~data_n_i;
        end
        to_analog_o.PSM_VDR_SELB = ~to_analog_o.PSM_VDR_SEL;
        to_analog_o.PSM_VSS_SELB = ~to_analog_o.PSM_VSS_SEL;
        to_analog_o.PSM_VRST_SELB = ~to_analog_o.PSM_VRST_SEL;

        if (!mac_en_i) begin
            to_analog_o.NSM_VDR_SEL = 0;
            to_analog_o.NSM_VSS_SEL = 0;
            to_analog_o.NSM_VRST_SEL = '1; // '1 = all ones
        end else begin
            to_analog_o.NSM_VDR_SEL = data_n_i & ~data_p_i; // only this part is different
            to_analog_o.NSM_VSS_SEL = data_p_i & ~data_n_i; // only this part is different
            to_analog_o.NSM_VRST_SEL = ~data_p_i & ~data_n_i;
        end
        to_analog_o.NSM_VDR_SELB = ~to_analog_o.NSM_VDR_SEL;
        to_analog_o.NSM_VSS_SELB = ~to_analog_o.NSM_VSS_SEL;
        to_analog_o.NSM_VRST_SELB = ~to_analog_o.NSM_VRST_SEL;
    end
end

// SRAM WRITES AND READS 
always_comb begin : WcSignals
    wc_write = to_sram_rq_wr && to_sram_rq_valid;
    wc_read = ~to_sram_rq_wr && to_sram_rq_valid;
end

logic wr_controller_ready;
assign from_sram_rq_ready = wr_controller_ready;

wr_controller #(
    .numRows                (numRows),
    .numCols                (numCols)
) u_wr_controller (
    .clk                    (clk),
    .nrst                   (nrst),

    .write_i                (wc_write),    
    .read_i                 (wc_read),     
    .wr_bus_sel_i           (wr_bus_sel_i),
    .addr_i                 (to_sram_addr),     
    .done                   (wc_done),  
    .ready                  (wr_controller_ready), 

    .wr_data_i              (to_sram_wr_data),
    .wr_data_q              (to_analog_o.WR_DATA),
    
    // SRAM interface signals
    .c3sram_w2b_o          (to_analog_o.WRITE),
    .c3sram_csel_o         (to_analog_o.CSEL),
    .c3sram_saen_o         (to_analog_o.SAEN),
    .c3sram_nprecharge_o   (to_analog_o.PCH),
    .c3sram_wl_o           (to_analog_o.WL)
);

`ifdef TRACK_STATISTICS

always_ff @( posedge clk ) begin : statisticsTracker
    // If mac is enabled, the ADCs and the array performs MAC no matter what
    if (mac_en_i) stats.statSeqAccMacs++;
    if (wc_write) stats.statSeqAccWeightWrites++;
    // currently we don't track reads, I mean who needs to for an IMC accelerator?
end

`endif

always_ff @( posedge clk or negedge nrst ) begin : RdDataHandler
    if (!nrst) begin
        from_sram_rd_data <= 0;
        from_sram_rd_valid <= 0;
    end else begin
        from_sram_rd_data <= from_analog_i.SA_OUT;
        from_sram_rd_valid <= wc_done;
    end
end

// ADC INTERFACE 
always_comb begin : AdcInterface
    if (clk && mac_en_i) begin // only allow negative feedback if MAC is enabled (this is power intensive)
        to_analog_o.NF = '1;
        to_analog_o.R2A = '1;
        to_analog_o.M2A = 0;
    end else begin
        to_analog_o.NF = 0;
        to_analog_o.R2A = 0;
        to_analog_o.M2A = '1;
    end
    to_analog_o.NFB = ~to_analog_o.NF;
    to_analog_o.M2AB = ~to_analog_o.M2A;
    to_analog_o.R2AB = ~to_analog_o.R2A;
end
always_ff @( posedge clk or negedge nrst ) begin : AdcOutRegistered
    if (!nrst) begin 
        adc_out_o <= 0;
    end else begin
        adc_out_o <= adc_out_encoded;
    end
end
generate
    if (numAdcBits == 4) begin : g_adc_decode_therm
        // Legacy 4-bit thermometer decode (the synthesised comparator count).
        always_comb begin : AdcEncoderLogic
            for (int i = 0; i < outputElements; i++) begin
                casez (adc_out[i])
                    15'b000_0000_0000_0000: adc_out_encoded[i] = -8; // 8 // 0000
                    15'b000_0000_0000_0001: adc_out_encoded[i] = -7; // 9 // 0001
                    15'b000_0000_0000_001?: adc_out_encoded[i] = -6; // A // 0003
                    15'b000_0000_0000_01??: adc_out_encoded[i] = -5; // B // 0007
                    15'b000_0000_0000_1???: adc_out_encoded[i] = -4; // C // 000F
                    15'b000_0000_0001_????: adc_out_encoded[i] = -3; // D // 001F
                    15'b000_0000_001?_????: adc_out_encoded[i] = -2; // E // 003F
                    15'b000_0000_01??_????: adc_out_encoded[i] = -1; // F // 007F
                    15'b000_0000_1???_????: adc_out_encoded[i] = 0;  // 0 // 00FF
                    15'b000_0001_????_????: adc_out_encoded[i] = 1;  // 1 // 01FF
                    15'b000_001?_????_????: adc_out_encoded[i] = 2;  // 2 // 03FF
                    15'b000_01??_????_????: adc_out_encoded[i] = 3;  // 3 // 07FF
                    15'b000_1???_????_????: adc_out_encoded[i] = 4;  // 4 // 0FFF
                    15'b001_????_????_????: adc_out_encoded[i] = 5;  // 5 // 1FFF
                    15'b01?_????_????_????: adc_out_encoded[i] = 6;  // 6 // 3FFF
                    15'b1??_????_????_????: adc_out_encoded[i] = 7;  // 7 // 7FFF
                    default: adc_out_encoded[i] = 0;
                endcase
            end
        end
    end else begin : g_adc_decode_code
        // Wider behavioural converter: the code is already the answer.
        always_comb begin : AdcCodeLogic
            for (int i = 0; i < outputElements; i++) begin
                adc_out_encoded[i] = from_analog_i.ADC_CODE[i][numAdcBits-1:0];
            end
        end
    end
endgenerate

endmodule