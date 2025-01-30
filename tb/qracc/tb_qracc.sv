//Verilog HDL for "test_caps", "tb_q_redis", "systemVerilog"
// as

`timescale 1ns/1ps

import qracc_pkg::*;

`define NUM_ADC_REF_RANGE_SHIFTS 2

module tb_qracc #(
    parameter SRAM_ROWS = 128,
    parameter SRAM_COLS = 32,
    parameter xBits = 2, // Ternary bits + 1
    parameter xBatches = 10,
    parameter numAdcBits = 4,
    parameter numCfgBits = 8,
    parameter macMode = 0
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

logic [numCfgBits-1:0] n_input_bits_cfg;
logic [numCfgBits-1:0] n_adc_bits_cfg;
logic mode_cfg;

logic clk;
logic nrst;
logic [numCols-1:0][numAdcBits-1:0] adc_out;
logic [numCols-1:0] sa_out;
logic [numRows-1:0] data_p_i;
logic [numRows-1:0] data_n_i;
logic signed [numRows-1:0][xBits-1:0] x_data;

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

logic rq_wr;
logic rq_valid;
logic rq_ready;
logic rd_valid;
logic [numCols-1:0] rd_data;
logic [numCols-1:0] wr_data;
logic [$clog2(numRows)-1:0] addr;
from_sram_t from_sram;
to_sram_t to_sram;

assign to_sram.rq_wr_i = rq_wr;
assign to_sram.rq_valid_i = rq_valid;
assign rq_ready = from_sram.rq_ready_o;
assign rd_valid = from_sram.rd_valid_o;
assign rd_data = from_sram.rd_data_o;
assign to_sram.wr_data_i = wr_data;
assign to_sram.addr_i = addr;

logic mac_en;
qracc_config_t qracc_cfg;

//////////////////////
// MODULE INSTANTIATION
//////////////////////

// Instantiate both modules and connect their interfaces
qr_acc_wrapper #(
    .numRows(numRows),
    .numCols(numCols),
    .numAdcBits(numAdcBits)
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
    .from_sram(from_sram),
    .to_sram(to_sram)
);

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

twos_to_bipolar #(
    .inBits(2),
    .numLanes(numRows)
) u_twos_to_bipolar (
    .twos(x_data),
    .bipolar_p(data_p_i),
    .bipolar_n(data_n_i)
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

//////////////////////
// TESTBENCH THINGS
//////////////////////

logic [numCols-1:0] flag;
int f_w,f_x,f_wx,f_adc_out;
int scan_data; 

// Clock Generation
always #(CLK_PERIOD/2) clk = ~clk;
initial begin
    clk = 0; 
end

// Waveform dumping
`ifdef SYNOPSYS
initial begin
    $vcdplusfile("tb_qracc.vpd");
    $vcdpluson();
    $vcdplusmemon();
    $dumpvars(0);
end
`endif
initial begin
    $dumpfile("tb_qracc.vcd");
    $dumpvars(0);
end

task print_adc_out;
    $write("[");
    for (int k = 0; k < numCols; k++) begin
        $write("%d,", $signed(adc_out[k]));
    end
    $display("]");
endtask

task save_adc_out;
    for (int k = 0; k < numCols; k++) begin
        $fwrite(f_adc_out, "%d ", $signed(adc_out[k]));
    end
    $fwrite(f_adc_out, "\n");
endtask

// yes my directory is visible, but i do not care.
static string path = "/home/lquizon/lawrence-workspace/SRAM_test/qrAcc2/qr_acc_2_digital/tb/qracc/inputs/";

initial begin

    test_phase = P_INIT;

    qracc_cfg.binary_cfg = macMode;
    if (qracc_cfg.binary_cfg == 1) $display("MAC MODE: BINARY");
    else $display("MAC MODE: BIPOLAR");

    // Open files        
    f_w = $fopen({path, "w.txt"}, "r");
    f_x = $fopen({path, "x.txt"}, "r");
    f_wx = $fopen({path, "wx_4b.txt"}, "r");

    `ifdef AMS
        if (qracc_cfg.binary_cfg == 1) f_adc_out = $fopen({path, "adc_out_ams_binary.txt"}, "w");
        else f_adc_out = $fopen({path, "adc_out_ams_bipolar.txt"}, "w");
    `else
        f_adc_out = $fopen({path, "adc_out_rtl.txt"}, "w");
    `endif

    // Initialize
    flag = 0;
    nrst = 0;
    wr_data = 0;
    mac_en = 0;
    x_data = 0; // To prevent X propagation
    
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
        for (int i = 0; i < numRows; i++) begin
            $fscanf(f_x, "%d", x_data[i]);
        end
        for (int i = 0; i < xBits-1; i++) begin
            #(CLK_PERIOD);
            print_adc_out();
            save_adc_out();
        end
    end
    `endif
    
    mac_en = 0;

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
