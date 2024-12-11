
// Wraps the analog QR accelerator
// Performs a 1-bit bipolar MAC operation with parametrizable output precision

module qr_acc_wrapper #(
    parameter numRows = 128,
    parameter numCols = 1,
    parameter numAdcBits = 4,
    parameter numCfgBits = 8
) ( 
    input clk,
    input nrst,

    // CONFIG
    input [numCfgBits-1:0] n_input_bits_cfg,
    input [numCfgBits-1:0] n_adc_bits_cfg,

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
    output logic [numCols-1:0] PCH,
    output logic [numCols-1:0] WR_DATA,
    output logic [numCols-1:0] WRITE,
    output logic [numCols-1:0] CSEL,
    output logic [numCols-1:0] SAEN,

    // ANALOG INTERFACE : ADC
    input [numCols-1:0][numAdcBits-1:0] ADC_OUT,
    output logic [numCols-1:0] NF,
    output logic [numCols-1:0] NFB,
    output logic [numCols-1:0] M2A,
    output logic [numCols-1:0] M2AB,
    output logic [numCols-1:0] R2A,
    output logic [numCols-1:0] R2AB,

    // DIGITAL INTERFACE: MAC
    output logic [numCols-1:0][numAdcBits-1:0] adc_out_o,
    input logic mac_en_i,
    input logic [numRows-1:0] data_p_i,
    input logic [numRows-1:0] data_n_i,
    
    // DIGITAL INTERFACE: SRAM
    input logic rq_wr_i, // write or read request
    input logic rq_valid_i, // request is valid
    output logic rq_ready_o, // if ready and valid, request is taken
    output logic rd_valid_o, // once asserted, rdata is valid for read requests
    output logic [numCols-1:0] rd_data_o,
    input logic [numCols-1:0] wr_data_i,
    input logic [$clog2(numRows)-1:0] addr_i
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
always_comb begin : WcSignals
    wc_write = rq_wr_i && rq_valid_i;
    wc_read = ~rq_wr_i && rq_valid_i;
    WR_DATA = wr_data_i;
end
wr_controller #(
    .numRows                (128),
    .numCols                (1)
) u_wr_controller(
    .clk                    (clk),
    .nrst                   (nrst),

    .write_i                (wc_write),    
    .read_i                 (wc_read),     
    .addr_i                 (addr_i),     
    .done                   (rd_valid_o),  
    .ready                  (rq_ready_o), 
    
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
    end else begin
        rd_data_o <= SA_OUT;
    end
end

// ADC INTERFACE 
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
        adc_out_o <= ADC_OUT;
    end
end

endmodule