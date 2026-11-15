//Verilog HDL for "test_caps", "tb_q_redis", "systemVerilog"
// as

`timescale 1ns/1ps

import qracc_pkg::*;

`define NUM_ADC_REF_RANGE_SHIFTS 1

module tb_qracc #(
    parameter SRAM_ROWS = 128,
    parameter SRAM_COLS = 32,
    parameter xBits = 2, // Ternary bits + 1
    parameter xBatches = 10,
    parameter numAdcBits = 4,
    parameter int numPlanes = 8,
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

to_analog_t to_analog [numPlanes-1:0];
from_analog_t from_analog [numPlanes-1:0];

logic [numCfgBits-1:0] n_input_bits_cfg;
logic [numCfgBits-1:0] n_adc_bits_cfg;
logic mode_cfg;

logic clk;
logic nrst;
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
genvar pw;
generate
    for (pw = 0; pw < numPlanes; pw++) begin : g_wrap
        qr_acc_wrapper #(
            .numRows(numRows),
            .numCols(numCols),
            .numAdcBits(numAdcBits)
        ) u_qr_acc_wrapper (
            .clk(clk),
            .nrst(nrst),
            // CONFIG
            .cfg(qracc_cfg),
            
            .to_analog_o(to_analog[pw]),
            .from_analog_i(from_analog[pw]),

            // DIGITAL INTERFACE: MAC
            .adc_out_o(plane_adc_out[pw]),
            .mac_en_i(mac_en),
            .data_p_i(data_p_i),
            .data_n_i(data_n_i),
            // DIGITAL INTERFACE: SRAM
            .to_sram_rq_wr(to_sram.rq_wr_i),
            .to_sram_rq_valid(to_sram.rq_valid_i),
            .to_sram_wr_data(to_sram.wr_data_i),
            .to_sram_addr(to_sram.addr_i),
            .from_sram_rq_ready(from_sram_rq_ready_plane[pw]),
            .from_sram_rd_valid(from_sram_rd_valid_plane[pw]),
            .from_sram_rd_data(from_sram_rd_data_plane[pw])
        );
    end
endgenerate

logic [numCols-1:0][numAdcBits-1:0] plane_adc_out [numPlanes-1:0];
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
assign PSM_VDR_SEL = to_analog[0].PSM_VDR_SEL;
assign PSM_VDR_SELB = to_analog[0].PSM_VDR_SELB;
assign PSM_VSS_SEL = to_analog[0].PSM_VSS_SEL;
assign PSM_VSS_SELB = to_analog[0].PSM_VSS_SELB;
assign PSM_VRST_SEL = to_analog[0].PSM_VRST_SEL;
assign PSM_VRST_SELB = to_analog[0].PSM_VRST_SELB;
assign NSM_VDR_SEL = to_analog[0].NSM_VDR_SEL;
assign NSM_VDR_SELB = to_analog[0].NSM_VDR_SELB;
assign NSM_VSS_SEL = to_analog[0].NSM_VSS_SEL;
assign NSM_VSS_SELB = to_analog[0].NSM_VSS_SELB;
assign NSM_VRST_SEL = to_analog[0].NSM_VRST_SEL;
assign NSM_VRST_SELB = to_analog[0].NSM_VRST_SELB;

assign from_analog[0].SA_OUT = SA_OUT;
assign WL = to_analog[0].WL;
assign PCH = to_analog[0].PCH;
assign WR_DATA = to_analog[0].WR_DATA;
assign WRITE = to_analog[0].WRITE;
assign CSEL = to_analog[0].CSEL;
assign SAEN = to_analog[0].SAEN;
// VERILATOR FIX: transparent latch to hold valid ADC output during clk HIGH phase
`ifdef VERILATOR
logic [compCount*numCols-1:0] ADC_OUT_held;
always_latch begin
    if (!clk) ADC_OUT_held = ADC_OUT;
end
genvar p;
generate
    for (p = 0; p < numPlanes; p++) begin : g_from_analog_adc
        assign from_analog[p].ADC_OUT = ADC_OUT_held;
    end
endgenerate
`else
genvar p;
generate
    for (p = 0; p < numPlanes; p++) begin : g_from_analog_adc
        assign from_analog[p].ADC_OUT = ADC_OUT;
    end
endgenerate
`endif
assign NF = to_analog[0].NF;
assign NFB = to_analog[0].NFB;
assign M2A = to_analog[0].M2A;
assign M2AB = to_analog[0].M2AB;
assign R2A = to_analog[0].R2A;
assign R2AB = to_analog[0].R2AB;
assign CLK = to_analog[0].CLK;

ts_qracc #(
    .numRows(SRAM_ROWS),
    .numCols(SRAM_COLS),
    .numAdcBits(numAdcBits)
) u_ts_qracc (
    .adc_ref_range_shifts(qracc_cfg.adc_ref_range_shifts),
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

// Full-width bipolar outputs (inBits wide per lane), then extract bit 0 for 1-bit data lines.
// This avoids a packed-array width mismatch that VCS handles per-element but Verilator does not.
logic [numRows-1:0][xBits-1:0] bipolar_p_full;
logic [numRows-1:0][xBits-1:0] bipolar_n_full;

twos_to_bipolar #(
    .inBits(xBits),
    .numLanes(numRows)
) u_twos_to_bipolar (
    .twos(x_data),
    .input_bits(4'(xBits)),
    .bipolar_p(bipolar_p_full),
    .bipolar_n(bipolar_n_full)
);

always_comb begin
    for (int i = 0; i < numRows; i++) begin
        data_p_i[i] = bipolar_p_full[i][0];
        data_n_i[i] = bipolar_n_full[i][0];
    end
end

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
`ifndef SYNOPSYS
initial begin
    $dumpfile("tb_qracc.vcd");
    $dumpvars(0);
end
`endif

task print_adc_out;
    $write("[");
    for (int k = 0; k < numCols; k++) begin
        $write("%d,", $signed(plane_adc_out[0][k]));
    end
    $display("]");
endtask

task save_adc_out;
    for (int k = 0; k < numCols; k++) begin
        $fwrite(f_adc_out, "%d ", $signed(plane_adc_out[0][k]));
    end
    $fwrite(f_adc_out, "\n");
endtask

// File paths use relative paths from the simulation directory (sims/)
static string path = "../tb/qracc/inputs/";

initial begin

    test_phase = P_INIT;

    qracc_cfg.binary_cfg = macMode;
    qracc_cfg.adc_ref_range_shifts = `NUM_ADC_REF_RANGE_SHIFTS;
    if (qracc_cfg.binary_cfg == 1) $display("MAC MODE: BINARY");
    else $display("MAC MODE: BIPOLAR");

    // Open files        
    f_w = $fopen({path, "w.txt"}, "r");
    if (f_w == 0) begin
        $display("[TB ERROR] cannot open input file %s", {path, "w.txt"});
        $fatal(1, "missing input file: generate it with pytest (see README) or provide it");
    end
    f_x = $fopen({path, "x.txt"}, "r");
    if (f_x == 0) begin
        $display("[TB ERROR] cannot open input file %s", {path, "x.txt"});
        $fatal(1, "missing input file: generate it with pytest (see README) or provide it");
    end
    f_wx = $fopen({path, "wx_4b.txt"}, "r");
    if (f_wx == 0) begin
        $display("[TB ERROR] cannot open input file %s", {path, "wx_4b.txt"});
        $fatal(1, "missing input file: generate it with pytest (see README) or provide it");
    end

    `ifdef AMS
        if (qracc_cfg.binary_cfg == 1) begin
            f_adc_out = $fopen({path, "adc_out_ams_binary.txt"}, "w");
            if (f_adc_out == 0) begin
                $display("[TB ERROR] cannot create output file %s", {path, "adc_out_ams_binary.txt"});
                $fatal(1, "cannot create output file");
            end
        end
        else begin
            f_adc_out = $fopen({path, "adc_out_ams_bipolar.txt"}, "w");
            if (f_adc_out == 0) begin
                $display("[TB ERROR] cannot create output file %s", {path, "adc_out_ams_bipolar.txt"});
                $fatal(1, "cannot create output file");
            end
        end
    `else
        if (qracc_cfg.binary_cfg == 1) begin
            f_adc_out = $fopen({path, "adc_out_rtl_binary.txt"}, "w");
            if (f_adc_out == 0) begin
                $display("[TB ERROR] cannot create output file %s", {path, "adc_out_rtl_binary.txt"});
                $fatal(1, "cannot create output file");
            end
        end
        else begin
            f_adc_out = $fopen({path, "adc_out_rtl_bipolar.txt"}, "w");
            if (f_adc_out == 0) begin
                $display("[TB ERROR] cannot create output file %s", {path, "adc_out_rtl_bipolar.txt"});
                $fatal(1, "cannot create output file");
            end
        end
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
            int tmp;
            $fscanf(f_x, "%d", tmp);
            x_data[i] = tmp[xBits-1:0];
        end
        `ifdef VERILATOR
        // Wait for negedge so the ADC latch captures the new value
        @(negedge clk);
        #1;
        `endif
        for (int i = 0; i < xBits-1; i++) begin
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
