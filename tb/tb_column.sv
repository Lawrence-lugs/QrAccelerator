//Verilog HDL for "test_caps", "tb_q_redis", "systemVerilog"

`timescale 1ns/1ps

import qracc_pkg::*;

module tb_column #(
    parameter SRAM_ROWS = 128,
    parameter SRAM_COLS = 1,
    parameter xBits = 2, // Ternary bits + 1
    parameter xBatches = 10,
    parameter numAdcBits = 4,
    parameter numCfgBits = 8,
    parameter macMode = 1
) ( 
    
);

/////////////
// PARAMETERS
/////////////

parameter numRows = SRAM_ROWS;
parameter numCols = SRAM_COLS;
localparam CLK_PERIOD = 20;
localparam compCount = (2**numAdcBits)-1; // An ADC only has 2^numAdcBits-1 comparators

/////////////
// SIGNALS
/////////////

to_analog_t to_analog;
from_analog_t from_analog;

logic [numRows-1:0] VDR_SEL;
logic [numRows-1:0] VDR_SELB;
logic [numRows-1:0] VSS_SEL;
logic [numRows-1:0] VSS_SELB;
logic [numRows-1:0] VRST_SEL;
logic [numRows-1:0] VRST_SELB;
logic [numCols-1:0] SA_OUT;
logic [numRows-1:0] WL;
logic PCH;
logic [numCols-1:0] WR_DATA;
logic WRITE;
logic [numCols-1:0] CSEL;
logic SAEN;
logic [compCount*numCols-1:0] ADC_OUT;
logic NF;
logic NFB;
logic M2A;
logic M2AB;
logic R2A;
logic R2AB;
logic CLK;

// We need to do this because
// it's illegal to connect VAMS electrical to structs
assign VDR_SEL = to_analog.VDR_SEL;
assign VDR_SELB = to_analog.VDR_SELB;
assign VSS_SEL = to_analog.VSS_SEL;
assign VSS_SELB = to_analog.VSS_SELB;
assign VRST_SEL = to_analog.VRST_SEL;
assign VRST_SELB = to_analog.VRST_SELB;
assign from_analog.SA_OUT = SA_OUT;
assign WL = to_analog.WL;
assign PCH = to_analog.PCH;
assign WR_DATA = to_analog.WR_DATA;
assign WRITE = to_analog.WRITE;
assign CSEL = to_analog.CSEL;
assign SAEN = to_analog.SAEN;
assign from_analog.ADC_OUT = ADC_OUT;
assign NF = to_analog.NF;
assign NFB = to_analog.NFB;
assign M2A = to_analog.M2A;
assign M2AB = to_analog.M2AB;
assign R2A = to_analog.R2A;
assign R2AB = to_analog.R2AB;
assign CLK = to_analog.CLK;

logic [numCfgBits-1:0] n_input_bits_cfg;
logic [numCfgBits-1:0] n_adc_bits_cfg;

logic clk;
logic nrst;
logic [numCols-1:0][numAdcBits-1:0] adc_out;
logic [numCols-1:0] sa_out;
logic [numRows-1:0] data_p_i;
logic [numRows-1:0] data_n_i;

integer i;

logic mac_en;
logic rq_wr;
logic rq_valid;
logic rq_ready;
logic rd_valid;
logic [numCols-1:0] rd_data;
logic [numCols-1:0] wr_data;
logic [$clog2(numRows)-1:0] addr;
qracc_config_t qracc_cfg;

//////////////////////
// MODULE INSTANTIATION
//////////////////////

// Instantiate both modules and connect their interfaces
qr_acc_wrapper #(
    .numRows(numRows),
    .numCols(numCols),
    .numAdcBits(numAdcBits),
    .numCfgBits(numCfgBits)
) u_qr_acc_wrapper (
    .clk(clk),
    .nrst(nrst),
    // CONFIG
    .cfg(qracc_cfg),

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

task sram_write(
    input logic [$clog2(numRows)-1:0] t_addr,
    input logic [numCols-1:0] t_data
);
    // set address
    addr = t_addr;
    wr_data = t_data;
    // set write request
    rq_wr = 1;
    rq_valid = 1;
    $write("SRAM WAITING TO WRITE ADDR: %d, DATA: %d... ", t_addr, wr_data);
    while (!rq_ready) #(CLK_PERIOD);
    #(CLK_PERIOD);
    $display("SUCCESSFUL");
    // set valid
    rq_valid = 0;
endtask

task sram_read(
    input logic [$clog2(numRows)-1:0] t_addr
);
    // set address
    addr = t_addr;
    // set write request
    rq_wr = 0;
    rq_valid = 1;
    $write("SRAM WAITING FOR READ REQUEST @ ADDR: %d,", t_addr);
    while (!rq_ready) #(CLK_PERIOD);
    #(CLK_PERIOD);
    // set valid
    rq_valid = 0;
    $write("WAITING... ");
    while (!rd_valid) #(CLK_PERIOD);
    $display("SUCCESSFUL. DATA: %d", rd_data);
endtask

ts_column u_ts_column (
    // ANALOG INTERFACE : SWITCH MATRIX
    .VDR_SEL(vdr_sel_int),
    .VDR_SELB(vdr_selb_int),
    .VSS_SEL(vss_sel_int),
    .VSS_SELB(vss_selb_int),
    .VRST_SEL(vrst_sel_int),
    .VRST_SELB(vrst_selb_int),
    // ANALOG INTERFACE : SRAM
    .SA_OUT(sa_out_int),
    .WL(wl_int),
    .PCH(pch_int),
    .WR_DATA(wr_data_int),
    .WRITE(write_int),
    .CSEL(csel_int),
    .SAEN(saen_int),
    // ANALOG INTERFACE : ADC
    .ADC_OUT(adc_out_int),
    .NF(nf_int),
    .NFB(nfb_int),
    .M2A(m2a_int),

    .M2AB(m2ab_int),
    .R2A(r2a_int),
    .R2AB(r2ab_int),
    .CLK(clk)
);

//////////////////////
// TESTBENCH THINGS
//////////////////////

// Clock Generation
always #(CLK_PERIOD/2) clk = ~clk;
initial begin
    clk = 0; 
end

// VCD generation
initial begin
    $dumpfile("dumps/tb_column.vcd");
    $dumpvars();
end

logic [numCols-1:0] flag;

initial begin

    data_n_i = -1;
    data_p_i = 0;
    flag = 0;
    nrst = 0;
    wr_data = 0;
    mac_en = 0;
    
    #(CLK_PERIOD*2);
    nrst = 1;
    #(CLK_PERIOD*2);

    `ifndef SKIP_WRITES 

    $display("Writing into SRAM...");
    for (int i = 0; i < numRows; i=i+1) begin
        sram_write( 
            .t_addr(i),
            .t_data(flag)
        );
    end
    
    $display("Reading from SRAM...");
    for (int i = 0; i < numRows; i++) begin
        sram_read( 
            .t_addr(i)
        );
    end

    `endif

    mac_en = 1;
    #(CLK_PERIOD*5); // Allow initial voltage transients to settle

    // Test range from VSS to VRST
    for (int i = 0; i < SRAM_ROWS; i++) begin
        data_n_i = {data_n_i[126:0], 1'b0};
        $display("ADC_OUT: %d", adc_out);
        #(CLK_PERIOD);
    end

    // Test range from VRST to VDR
    for (int i = 0; i < SRAM_ROWS; i++) begin
        data_p_i = {data_p_i[126:0], 1'b1};
        $display("ADC_OUT: %d", adc_out);
        #(CLK_PERIOD);
    end

    #(CLK_PERIOD*2);

    $display("TEST SUCCESS");

    $finish();
end

// FREEZE WATCHDOG
initial begin
    #(CLK_PERIOD*50000); // after 1ms
    $display("WATCHDOG TIMED OUT");
    $finish();
end

endmodule
