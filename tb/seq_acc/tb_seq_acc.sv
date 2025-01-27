//Verilog HDL for "test_caps", "tb_q_redis", "systemVerilog"

`timescale 1ns/1ps

import qracc_pkg::*;

module tb_seq_acc #(
    parameter SRAM_ROWS = 128,
    parameter SRAM_COLS = 32,
    parameter xBits = 5, // Ternary bits + 1
    parameter xBatches = 10,
    parameter numAdcBits = 4,
    parameter numCfgBits = 8,
    parameter macMode = 1,
    parameter outBits = 4
) ( 
    
);

/////////////
// PARAMETERS
/////////////

parameter numRows = SRAM_ROWS;
parameter numCols = SRAM_COLS;
localparam CLK_PERIOD = 20;
localparam compCount = (2**numAdcBits)-1; // An ADC only has 2^numAdcBits-1 comparators
localparam xTrits = xBits-1;

/////////////
// SIGNALS
/////////////

to_analog_t to_analog;
from_analog_t from_analog;

logic clk;
logic nrst;
logic signed [numRows-1:0][xBits-1:0] mac_data;
logic signed mac_data_valid;
logic signed [numCols-1:0][outBits-1:0] mac_result;

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
sram_itf #(
    .numRows(SRAM_ROWS),
    .numCols(SRAM_COLS)
) u_sram_itf ();

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
assign u_sram_itf.rq_wr_i = rq_wr;
assign u_sram_itf.rq_valid_i = rq_valid;
assign rq_ready = u_sram_itf.rq_ready_o;
assign rd_valid = u_sram_itf.rd_valid_o;
assign rd_data = u_sram_itf.rd_data_o;
assign u_sram_itf.wr_data_i = wr_data;
assign u_sram_itf.addr_i = addr;

//////////////////////
// MODULE INSTANTIATION
//////////////////////

// Instantiate both modules and connect their interfaces
seq_acc #(
    .inputBits(xBits),
    .inputElements(numRows),
    .outputBits(outBits),
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
    .sram_itf(u_sram_itf)
);

// TS = Test Schematic
// Cadence VAMS doesn't support structs
ts_qracc #(
    .numRows(SRAM_ROWS),
    .numCols(SRAM_COLS),
    .numAdcBits(numAdcBits)
) u_ts_qracc (
    .VDR_SEL(VDR_SEL),
    .VDR_SELB(VDR_SELB), 
    .VSS_SEL(VSS_SEL),
    .VSS_SELB(VSS_SELB),
    .VRST_SEL(VRST_SEL),
    .VRST_SELB(VRST_SELB),
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

//////////////////////
// TESTBENCH THINGS
//////////////////////

int f_w,f_x,f_wx,f_mac_out;
int scan_data; 

logic signed [outBits-1:0] mac_result_readable [numCols];

always_comb begin
    for (int i = 0; i < numCols; i++) begin
        mac_result_readable[i] = mac_result[i];
    end
end

// Keep reading the outputs
always @(posedge clk) begin
    if (valid_o) begin
        $write("[");
        for (int k = 0; k < numCols; k++) begin
            $write("%d,", $signed(mac_result[k]));
        end
        $display("]");
        for (int i = 0; i < numCols; i++) begin
            $fwrite(f_mac_out, "%d ", $signed(mac_result[i]));
        end
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
    $dumpvars(0);
end

// yes my directory is visible, but i do not care.
static string path = "/home/lquizon/lawrence-workspace/SRAM_test/qrAcc2/qr_acc_2_digital/tb/seq_acc/inputs/";

initial begin

    test_phase = P_INIT;
    cfg.binary_cfg = 0;

    // Open files        
    f_w = $fopen({path, "w.txt"}, "r");
    f_x = $fopen({path, "x.txt"}, "r");
    f_wx = $fopen({path, "wx_clipped.txt"}, "r");
    f_mac_out = $fopen({path, "mac_out.txt"}, "w");

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
