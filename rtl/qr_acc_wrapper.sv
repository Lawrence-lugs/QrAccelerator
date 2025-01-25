
// Wraps the analog QR accelerator
// Performs a 1-bit bipolar MAC operation with parametrizable output precision

import qracc_pkg::*;

module qr_acc_wrapper #(
    parameter numRows = 128,
    parameter numCols = 32,
    parameter numAdcBits = 4,
    parameter compCount = (2**numAdcBits)-1 // An ADC only has 2^numAdcBits-1 comparators
) ( 
    input clk,
    input nrst,

    // CONFIG
    input qracc_config_t cfg,

    input from_analog_t from_analog_i,
    output to_analog_t to_analog_o,

    // DIGITAL INTERFACE: MAC
    output logic [numCols-1:0][numAdcBits-1:0] adc_out_o,
    input mac_en_i,
    input [numRows-1:0] data_p_i,
    input [numRows-1:0] data_n_i,
    
    // DIGITAL INTERFACE: SRAM
    input rq_wr_i, // write or read request
    input rq_valid_i, // request is valid
    output logic rq_ready_o, // if ready and valid, request is taken
    output logic rd_valid_o, // once asserted, rdata is valid for read requests
    output logic [numCols-1:0] rd_data_o,
    input [numCols-1:0] wr_data_i,
    input [$clog2(numRows)-1:0] addr_i
);

logic wc_write;
logic wc_read;
logic wd_done;
logic [numCols-1:0][numAdcBits-1:0] adc_out_encoded;
logic [numCols-1:0][compCount-1:0] adc_out;

// ADC OUT -- realign flattened ADC output
assign adc_out = from_analog_i.ADC_OUT;

// SWITCH MATRIX SELECTS
always_comb begin : SwitchMatrixSelects
    if (clk && mac_en_i) begin
        to_analog_o.VDR_SEL = 0;
        to_analog_o.VSS_SEL = 0;
        to_analog_o.VRST_SEL = '1; // '1 = all ones
    end else begin
        to_analog_o.VDR_SEL = data_p_i & ~data_n_i;
        to_analog_o.VSS_SEL = data_n_i & ~data_p_i;
        to_analog_o.VRST_SEL = ~data_p_i & ~data_n_i;
    end
    to_analog_o.VDR_SELB = ~to_analog_o.VDR_SEL;
    to_analog_o.VSS_SELB = ~to_analog_o.VSS_SEL;
    to_analog_o.VRST_SELB = ~to_analog_o.VRST_SEL;
end

// SRAM WRITES AND READS 
always_comb begin : WcSignals
    wc_write = rq_wr_i && rq_valid_i;
    wc_read = ~rq_wr_i && rq_valid_i;
end
wr_controller #(
    .numRows                (numRows),
    .numCols                (numCols)
) u_wr_controller (
    .clk                    (clk),
    .nrst                   (nrst),

    .write_i                (wc_write),    
    .read_i                 (wc_read),     
    .addr_i                 (addr_i),     
    .done                   (wc_done),  
    .ready                  (rq_ready_o), 

    .wr_data_i              (wr_data_i),
    .wr_data_q              (to_analog_o.WR_DATA),
    
    // SRAM interface signals
    .c3sram_w2b_o          (to_analog_o.WRITE),
    .c3sram_csel_o         (to_analog_o.CSEL),
    .c3sram_saen_o         (to_analog_o.SAEN),
    .c3sram_nprecharge_o   (to_analog_o.PCH),
    .c3sram_wl_o           (to_analog_o.WL)
);
always_ff @( posedge clk or negedge nrst ) begin : RdDataHandler
    if (!nrst) begin
        rd_data_o <= 0;
        rd_valid_o <= 0;
    end else begin
        rd_data_o <= from_analog_i.SA_OUT;
        rd_valid_o <= wc_done;
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
always_comb begin : AdcEncoderLogic
    for (int i = 0; i < numCols; i++) begin
        casex (adc_out[i])
            15'b000_0000_0000_0000: adc_out_encoded[i] = -8; // 8 // 0000
            15'b000_0000_0000_0001: adc_out_encoded[i] = -7; // 9 // 0001
            15'b000_0000_0000_001x: adc_out_encoded[i] = -6; // A // 0003
            15'b000_0000_0000_01xx: adc_out_encoded[i] = -5; // B // 0007
            15'b000_0000_0000_1xxx: adc_out_encoded[i] = -4; // C // 000F
            15'b000_0000_0001_xxxx: adc_out_encoded[i] = -3; // D // 001F
            15'b000_0000_001x_xxxx: adc_out_encoded[i] = -2; // E // 003F
            15'b000_0000_01xx_xxxx: adc_out_encoded[i] = -1; // F // 007F
            15'b000_0000_1xxx_xxxx: adc_out_encoded[i] = 0;  // 0 // 00FF
            15'b000_0001_xxxx_xxxx: adc_out_encoded[i] = 1;  // 1 // 01FF
            15'b000_001x_xxxx_xxxx: adc_out_encoded[i] = 2;  // 2 // 03FF
            15'b000_01xx_xxxx_xxxx: adc_out_encoded[i] = 3;  // 3 // 07FF
            15'b000_1xxx_xxxx_xxxx: adc_out_encoded[i] = 4;  // 4 // 0FFF
            15'b001_xxxx_xxxx_xxxx: adc_out_encoded[i] = 5;  // 5 // 1FFF
            15'b01x_xxxx_xxxx_xxxx: adc_out_encoded[i] = 6;  // 6 // 3FFF
            15'b1xx_xxxx_xxxx_xxxx: adc_out_encoded[i] = 7;  // 7 // 7FFF
            default: adc_out_encoded[i] = 0;
        endcase
    end
end

endmodule