
// Wraps the analog QR accelerator
// Performs a 1-bit bipolar MAC operation with parametrizable output precision

module qr_acc_wrapper #(
    parameter numRows = 128,
    parameter numCols = 8,
    parameter numAdcBits = 4,
    parameter numCfgBits = 8
) ( 
    input clk,
    input nrst,

    // CONFIG
    input [numCfgBits-1:0] n_input_bits_cfg,
    input [numCfgBits-1:0] n_adc_bits_cfg,
    input binary_cfg, // binary or bipolar MAC

    // ANALOG INTERFACE : SWITCH MATRIX
    output logic [numRows-1:0] VDR_SEL,
    output logic [numRows-1:0] VDR_SELB,
    output logic [numRows-1:0] VSS_SEL,
    output logic [numRows-1:0] VSS_SELB,
    output logic [numRows-1:0] VRST_SEL,
    output logic [numRows-1:0] VRST_SELB,

    // ANALOG INTERFACE : SRAM
    input [numCols-1:0] SA_OUT,
    output logic [numRows-1:0] WL, 
    output logic PCH,
    output logic [numCols-1:0] WR_DATA,
    output logic WRITE,
    output logic [numCols-1:0] CSEL,
    output logic SAEN,

    // ANALOG INTERFACE : ADC
    input [numCols-1:0][(2**numAdcBits)-1:0] ADC_OUT, // comparator output pre-encoder
    output logic NF,
    output logic NFB,
    output logic M2A,
    output logic M2AB,
    output logic R2A,
    output logic R2AB,

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

// SWITCH MATRIX SELECTS
always_comb begin : SwitchMatrixSelects
    if (clk && mac_en_i) begin
        VDR_SEL = 0;
        VSS_SEL = 0;
        VRST_SEL = '1; // '1 = all ones
    end else begin
        VDR_SEL = data_p_i & ~data_n_i;
        VSS_SEL = data_n_i & ~data_p_i;
        VRST_SEL = ~data_p_i & ~data_n_i;
    end
    VDR_SELB = ~VDR_SEL;
    VSS_SELB = ~VSS_SEL;
    VRST_SELB = ~VRST_SEL;
end

// SRAM WRITES AND READS 
logic wc_write;
logic wc_read;
logic wd_done;
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
    .wr_data_q              (WR_DATA),
    
    // SRAM interface signals
    .c3sram_w2b_o          (WRITE),
    .c3sram_csel_o         (CSEL),
    .c3sram_saen_o         (SAEN),
    .c3sram_nprecharge_o   (PCH),
    .c3sram_wl_o           (WL)
);
always_ff @( posedge clk or negedge nrst ) begin : RdDataHandler
    if (!nrst) begin
        rd_data_o <= 0;
        rd_valid_o <= 0;
    end else begin
        rd_data_o <= SA_OUT;
        rd_valid_o <= wc_done;
    end
end

// ADC INTERFACE 
logic [numCols-1:0][numAdcBits-1:0] adc_out_encoded;
always_comb begin : AdcInterface
    if (clk && mac_en_i) begin // only allow negative feedback if MAC is enabled (this is power intensive)
        NF = '1;
        R2A = '1;
        M2A = 0;
    end else begin
        NF = 0;
        R2A = 0;
        M2A = '1;
    end
    NFB = ~NF;
    M2AB = ~M2A;
    R2AB = ~R2A;
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
        casex (ADC_OUT[i])
            15'b000_0000_0000_0000: adc_out_encoded[i] = -8; // 8
            15'b000_0000_0000_0001: adc_out_encoded[i] = -7; // 9
            15'b000_0000_0000_001x: adc_out_encoded[i] = -6; // A
            15'b000_0000_0000_01xx: adc_out_encoded[i] = -5; // B
            15'b000_0000_0000_1xxx: adc_out_encoded[i] = -4; // C
            15'b000_0000_0001_xxxx: adc_out_encoded[i] = -3; // D
            15'b000_0000_001x_xxxx: adc_out_encoded[i] = -2; // E
            15'b000_0000_01xx_xxxx: adc_out_encoded[i] = -1; // F
            15'b000_0000_1xxx_xxxx: adc_out_encoded[i] = 0;
            15'b000_0001_xxxx_xxxx: adc_out_encoded[i] = 1;
            15'b000_001x_xxxx_xxxx: adc_out_encoded[i] = 2;
            15'b000_01xx_xxxx_xxxx: adc_out_encoded[i] = 3;
            15'b000_1xxx_xxxx_xxxx: adc_out_encoded[i] = 4;
            15'b001_xxxx_xxxx_xxxx: adc_out_encoded[i] = 5;
            15'b01x_xxxx_xxxx_xxxx: adc_out_encoded[i] = 6;
            15'b1xx_xxxx_xxxx_xxxx: adc_out_encoded[i] = 7;
            default: adc_out_encoded[i] = 0;
        endcase
    end
end

endmodule