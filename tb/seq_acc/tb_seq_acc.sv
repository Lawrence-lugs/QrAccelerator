//Verilog HDL for "test_caps", "tb_q_redis", "systemVerilog"
// Adasdsd

`timescale 1ns/1ps

import qracc_pkg::*;

`define NUM_ADC_REF_RANGE_SHIFTS 1

module tb_seq_acc #(
    parameter SRAM_ROWS = 128,
    parameter SRAM_COLS = 32,
    parameter xBits = 4, // Ternary bits + 1
    parameter xBatches = 10,
    parameter numAdcBits = 4,
    parameter numCfgBits = 8,
    parameter macMode = 0,
    parameter outBits = 8,
    parameter unsignedActs = 0
) ( 
);

/////////////
// PARAMETERS
/////////////

parameter numRows = SRAM_ROWS;
parameter numCols = SRAM_COLS;
parameter maxInputBits = 9; // For max 8 trits
localparam CLK_PERIOD = 20;
localparam compCount = (2**numAdcBits)-1; // An ADC only has 2^numAdcBits-1 comparators
localparam xTrits = xBits-1;
// localparam accumulatorBits = (xTrits - 1) + numAdcBits + 1; // +1 from addition bit growth
// localparam accumulatorBits = 8;
localparam accumulatorBits = 16;

/////////////
// SIGNALS
/////////////

to_analog_t to_analog;
from_analog_t from_analog;

logic clk;
logic nrst;
logic signed [numRows-1:0][maxInputBits-1:0] mac_data;
// logic signed [numRows-1:0][15:0] mac_data;
logic signed mac_data_valid;
logic signed [numCols-1:0][accumulatorBits-1:0] mac_result;

integer i;

typedef enum logic [3:0] { 
    P_INIT,
    P_WRITE_WEIGHTS,
    P_READ_WEIGHTS,
    P_READ_X,
    P_PERFORM_MACS,
    P_DONE
} test_phase_t;

test_phase_t test_phase;
qracc_config_t cfg;

logic mac_en;
logic rq_wr;
logic rq_valid;
logic rq_ready;
logic rd_valid;
logic [numCols-1:0] rd_data;
logic [numCols-1:0] wr_data;
logic [$clog2(numRows)-1:0] addr;

logic [numRows-1:0] PSM_VDR_SEL;
logic [numRows-1:0] PSM_VDR_SELB;
logic [numRows-1:0] PSM_VSS_SEL;
logic [numRows-1:0] PSM_VSS_SELB;
logic [numRows-1:0] PSM_VRST_SEL;
logic [numRows-1:0] PSM_VRST_SELB;

logic [numRows-1:0] NSM_VDR_SEL;
logic [numRows-1:0] NSM_VDR_SELB;
logic [numRows-1:0] NSM_VSS_SEL;
logic [numRows-1:0] NSM_VSS_SELB;
logic [numRows-1:0] NSM_VRST_SEL;
logic [numRows-1:0] NSM_VRST_SELB;

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
from_sram_t from_sram;
to_sram_t to_sram;

// We need to do this because
// it's illegal to connect VAMS electrical to structs
assign PSM_VDR_SEL = to_analog.PSM_VDR_SEL;
assign PSM_VDR_SELB = to_analog.PSM_VDR_SELB;
assign PSM_VSS_SEL = to_analog.PSM_VSS_SEL;
assign PSM_VSS_SELB = to_analog.PSM_VSS_SELB;
assign PSM_VRST_SEL = to_analog.PSM_VRST_SEL;
assign PSM_VRST_SELB = to_analog.PSM_VRST_SELB;
assign NSM_VDR_SEL = to_analog.NSM_VDR_SEL;
assign NSM_VDR_SELB = to_analog.NSM_VDR_SELB;
assign NSM_VSS_SEL = to_analog.NSM_VSS_SEL;
assign NSM_VSS_SELB = to_analog.NSM_VSS_SELB;
assign NSM_VRST_SEL = to_analog.NSM_VRST_SEL;
assign NSM_VRST_SELB = to_analog.NSM_VRST_SELB;

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
assign to_sram.rq_wr_i = rq_wr;
assign to_sram.rq_valid_i = rq_valid;
assign rq_ready = from_sram.rq_ready_o;
assign rd_valid = from_sram.rd_valid_o;
assign rd_data = from_sram.rd_data_o;
assign to_sram.wr_data_i = wr_data;
assign to_sram.addr_i = addr;

//////////////////////
// MODULE INSTANTIATION
//////////////////////

// Instantiate both modules and connect their interfaces
seq_acc #(
    .maxInputBits(maxInputBits),
    .inputElements(numRows),
    // .outputBits(outBits),
    .outputElements(numCols),
    .adcBits(numAdcBits)
) u_seq_acc (
    .clk(clk),
    .nrst(nrst),
    
    .cfg(cfg),
    
    .mac_data_i(mac_data),
    .mac_valid_i(mac_data_valid),
    .ready_o(ready_o),
    .valid_o(valid_o),
    .mac_data_o(mac_result),
    
    // Passthrough Signals
    .to_analog_o(to_analog),
    .from_analog_i(from_analog),
    .from_sram(from_sram),
    .to_sram(to_sram)
);

// TS = Test Schematic
// Cadence VAMS doesn't support structs
ts_qracc #(
    .numRows(SRAM_ROWS),
    .numCols(SRAM_COLS),
    .numAdcBits(numAdcBits)
) u_ts_qracc (
    .PSM_VDR_SEL(PSM_VDR_SEL),
    .PSM_VDR_SELB(PSM_VDR_SELB),
    .PSM_VSS_SEL(PSM_VSS_SEL),
    .PSM_VSS_SELB(PSM_VSS_SELB),
    .PSM_VRST_SEL(PSM_VRST_SEL),
    .PSM_VRST_SELB(PSM_VRST_SELB),
    .NSM_VDR_SEL(NSM_VDR_SEL),
    .NSM_VDR_SELB(NSM_VDR_SELB),
    .NSM_VSS_SEL(NSM_VSS_SEL), 
    .NSM_VSS_SELB(NSM_VSS_SELB),
    .NSM_VRST_SEL(NSM_VRST_SEL),
    .NSM_VRST_SELB(NSM_VRST_SELB),
    .SA_OUT(SA_OUT),
    .WL(WL),
    .PCH(PCH),
    .WR_DATA(WR_DATA),
    .WRITE(WRITE),
    .CSEL(CSEL),
    .SAEN(SAEN),
    .ADC_OUT(ADC_OUT),
    .NF(NF),
    .NFB(NFB),
    .M2A(M2A),
    .M2AB(M2AB),
    .R2A(R2A),
    .R2AB(R2AB),
    .CLK(clk)
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
    $write("SRAM WRITE @ %d, DATA: %d... ", t_addr, wr_data);
    while (!rq_ready) #(CLK_PERIOD);
    #(CLK_PERIOD);
    $display("GD");
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
    $write("SRAM READ @ %d,", t_addr);
    while (!rq_ready) #(CLK_PERIOD);
    #(CLK_PERIOD);
    // set valid
    rq_valid = 0;
    $write("...");
    while (!rd_valid) #(CLK_PERIOD);
    $display("DATA: %d", rd_data);
endtask

task send_mac_request();
    mac_data_valid = 1;
    for (i = 0; i < numRows; i++) $fscanf(f_x, "%d", mac_data[i]);
    while (!ready_o) #(CLK_PERIOD); // Wait for request take
    #(CLK_PERIOD);
    mac_data_valid = 0;
endtask

task set_config();
    // Set config
    cfg.adc_ref_range_shifts = `NUM_ADC_REF_RANGE_SHIFTS;
    cfg.binary_cfg = macMode;
    cfg.unsigned_acts = unsignedActs;
    cfg.n_input_bits_cfg = xBits;
endtask

//////////////////////
// TESTBENCH THINGS
//////////////////////

int f_w,f_x,f_wx,f_mac_out;
int scan_data; 

// Keep reading the outputs
always @(posedge clk) begin
    if (valid_o) begin
        $write("[");
        for (int k = 0; k < numCols; k++) begin
            $write("%d,", $signed(mac_result[k]));
            $fwrite(f_mac_out, "%d ", $signed(mac_result[k]));
        end
        $display("]");
        $fwrite(f_mac_out, "\n");
    end
end

// Clock Generation
always #(CLK_PERIOD/2) clk = ~clk;
initial begin
    clk = 0; 
end

// Waveform dumping
`ifdef SYNOPSYS
initial begin
    $vcdplusfile("tb_seq_acc.vpd");
    $vcdpluson();
    $vcdplusmemon();
    $dumpvars(0);
end
`endif
initial begin
    $dumpfile("tb_seq_acc.vcd");
    $vcdplusmemon();
    $dumpvars(0);
end

// yes my directory is visible, but i do not care.
static string path = "/home/lquizon/lawrence-workspace/SRAM_test/qrAcc2/qr_acc_2_digital/tb/seq_acc/inputs/";

initial begin

    test_phase = P_INIT;
    
    // Set config
    set_config();

    if (cfg.binary_cfg == 1) $display("MAC MODE: BINARY");
    else $display("MAC MODE: BIPOLAR");

    // Open files        
    f_w = $fopen({path, "w.txt"}, "r");
    f_x = $fopen({path, "x.txt"}, "r");
    f_wx = $fopen({path, "wx_clipped.txt"}, "r");

    `ifdef AMS
        if (cfg.binary_cfg == 1) f_mac_out = $fopen({path, "mac_out_ams_binary.txt"}, "w");
        else f_mac_out = $fopen({path, "mac_out_ams_bipolar.txt"}, "w");
    `else
        if (cfg.binary_cfg == 1) f_mac_out = $fopen({path, "mac_out_rtl_binary.txt"}, "w");
        else f_mac_out = $fopen({path, "mac_out_rtl_bipolar.txt"}, "w");
    `endif

    // Initialize
    nrst = 0;
    wr_data = 0;
    mac_data_valid = 0;
    mac_data = 0;

    // Reset
    #(CLK_PERIOD*2);
    nrst = 1;
    #(CLK_PERIOD*2);

    // Read weights
    `ifndef SKIPWRITE
    test_phase = P_WRITE_WEIGHTS;
    $display("Reading weights...");
    $display("Writing into SRAM...");
    for (int i = 0; i < numRows; i=i+1) begin
        if ($fscanf(f_w, "%d", scan_data))
            sram_write( 
                .t_addr(i),
                .t_data(scan_data)
            );
    end
    `endif

    `ifndef SKIPREAD 
    test_phase = P_READ_WEIGHTS;
    $display("Reading from SRAM...");
    for (int i = 0; i < numRows; i++) begin
        sram_read( 
            .t_addr(i)
        );
    end
    `endif
    
    // Allow initial voltage transients to settle
    $display("Activating MAC...");
    test_phase = P_READ_X;
    mac_en = 1;
    #(CLK_PERIOD*5);

    $display("Reading X...");
    #(CLK_PERIOD);

    `ifndef SKIPMACS
    test_phase = P_PERFORM_MACS;
    $display("Performing MACs...");
    for (int h = 0; h < xBatches; h++) begin
        send_mac_request();
        // We do not need to read result here because it is 
        // done by the always block somewhere above
    end
    `endif

    while (!valid_o) #(CLK_PERIOD);

    #(CLK_PERIOD*10);

    $display("TEST SUCCESS");

    $finish();
end

// FREEZE WATCHDOG
initial begin
    #(CLK_PERIOD*50000); // after 1ms
    $display("ERROR: WATCHDOG TIMED OUT");
    $finish();
end

endmodule
