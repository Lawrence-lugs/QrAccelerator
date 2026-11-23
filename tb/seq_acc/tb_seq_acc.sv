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
    // ADC half-span in counts at adc_ref_range_shifts == 0 (power of two).
    parameter int adcFullScale = (1 << numAdcBits),
    parameter int adcShift = 1,
    parameter int numPlanes = 8,
    parameter int numBeatRows = 4,
    parameter int weightBits = 1,
    parameter int weightSigned = 0,
    // 0: legacy mode, one w.txt word replicated to every plane.
    // 1: multibit mode, w.txt holds numPlanes words per SRAM row.
    parameter int weightPlanes = 0,
    parameter int accumulatorBits = 16,
    // 1: hold mac_data_valid high across words (back-to-back streaming, as the
    // top-level controller does).  0: legacy one-shot requests with gaps.
    parameter int streamMacs = 0,
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
parameter maxInputBits = qrAccMaxInputBits; // For max 8 trits plus unsigned bit
localparam CLK_PERIOD = 20;
localparam compCount = (2**numAdcBits)-1; // An ADC only has 2^numAdcBits-1 comparators
localparam xTrits = xBits-1;
// localparam accumulatorBits = (xTrits - 1) + numAdcBits + 1; // +1 from addition bit growth


/////////////
// SIGNALS
/////////////

to_analog_t to_analog [numPlanes-1:0];
from_analog_t from_analog [numPlanes-1:0];

logic clk;
logic nrst;
logic signed [numRows-1:0][maxInputBits-1:0] mac_data;
// logic signed [numRows-1:0][15:0] mac_data;
logic signed mac_data_valid;
logic signed [numCols-1:0][accumulatorBits-1:0] mac_result;
logic ready_o;
logic valid_o;

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
logic [numBeatRows*numPlanes*numCols-1:0] wr_data_planes;
logic [$clog2(numRows)-1:0] addr;

// One analog test schematic per plane: each bit-plane has its own SRAM
// contents in the multibit configuration, so a single shared ts_qracc model
// would only ever see one plane's weights.
logic [numCols-1:0] SA_OUT [numPlanes-1:0];
logic [compCount*numCols-1:0] ADC_OUT [numPlanes-1:0];
logic signed [numCols-1:0][qrAccAdcCodeBits-1:0] ADC_CODE [numPlanes-1:0];

from_sram_t from_sram;
to_sram_t to_sram;

genvar p;
generate
    for (p = 0; p < numPlanes; p++) begin : g_plane_ts
        ts_qracc #(
            .numRows(SRAM_ROWS),
            .numCols(SRAM_COLS),
            .numAdcBits(numAdcBits),
            .adcFullScale(adcFullScale)
        ) u_ts_qracc (
            .adc_ref_range_shifts(cfg.adc_ref_range_shifts),
            .binary_cfg(cfg.binary_cfg),
            .PSM_VDR_SEL(to_analog[p].PSM_VDR_SEL),
            .PSM_VDR_SELB(to_analog[p].PSM_VDR_SELB),
            .PSM_VSS_SEL(to_analog[p].PSM_VSS_SEL),
            .PSM_VSS_SELB(to_analog[p].PSM_VSS_SELB),
            .PSM_VRST_SEL(to_analog[p].PSM_VRST_SEL),
            .PSM_VRST_SELB(to_analog[p].PSM_VRST_SELB),
            .NSM_VDR_SEL(to_analog[p].NSM_VDR_SEL),
            .NSM_VDR_SELB(to_analog[p].NSM_VDR_SELB),
            .NSM_VSS_SEL(to_analog[p].NSM_VSS_SEL),
            .NSM_VSS_SELB(to_analog[p].NSM_VSS_SELB),
            .NSM_VRST_SEL(to_analog[p].NSM_VRST_SEL),
            .NSM_VRST_SELB(to_analog[p].NSM_VRST_SELB),
            .SA_OUT(SA_OUT[p]),
            .WL(to_analog[p].WL),
            .PCH(to_analog[p].PCH),
            .WR_DATA(to_analog[p].WR_DATA),
            .WRITE(to_analog[p].WRITE),
            .CSEL(to_analog[p].CSEL),
            .SAEN(to_analog[p].SAEN),
            .ADC_OUT(ADC_OUT[p]),
            .ADC_CODE(ADC_CODE[p]),
            .NF(to_analog[p].NF),
            .NFB(to_analog[p].NFB),
            .M2A(to_analog[p].M2A),
            .M2AB(to_analog[p].M2AB),
            .R2A(to_analog[p].R2A),
            .R2AB(to_analog[p].R2AB),
            .CLK(clk)
        );

        assign from_analog[p].SA_OUT = SA_OUT[p];
        assign from_analog[p].ADC_CODE = ADC_CODE[p];
        // Wide behavioural converters use the digital code tap; the physical
        // thermometer bus only exists for the synthesised 4-bit ADC.
        if (numAdcBits == 4) begin : g_therm
            assign from_analog[p].ADC_OUT = ADC_OUT[p];
        end
    end
endgenerate

assign to_sram.rq_wr_i = rq_wr;
assign to_sram.rq_valid_i = rq_valid;
assign rq_ready = from_sram.rq_ready_o;
assign rd_valid = from_sram.rd_valid_o;
assign rd_data = from_sram.rd_data_o;

// wr_data_planes is assembled per row in the weight-load loop below: the
// legacy path replicates one word across all planes, the multibit path reads
// one word per plane.

assign to_sram.addr_i = addr;

//////////////////////
// MODULE INSTANTIATION
//////////////////////

// Instantiate both modules and connect their interfaces
seq_acc #(
    .maxInputBits(maxInputBits),
    .inputElements(numRows),
    // .outputBits(outBits),
    .numCols(numCols),
    .outputElements(numCols),
    .adcBits(numAdcBits),
    .adcFullScale(adcFullScale),
    .accumulatorBits(accumulatorBits)
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
    .to_sram_rq_wr(to_sram.rq_wr_i),
    .to_sram_rq_valid(to_sram.rq_valid_i),
    .wr_bus_sel_i(cfg.wr_bus_sel),
    .to_sram_wr_data(wr_data_planes),
    .to_sram_addr(to_sram.addr_i),
    .from_sram_rq_ready(from_sram.rq_ready_o),
    .from_sram_rd_valid(from_sram.rd_valid_o),
    .from_sram_rd_data(from_sram.rd_data_o)
);

task sram_write(
    input logic [$clog2(numRows)-1:0] t_addr,
    input logic [numCols-1:0] t_data
);
    // Drive on the falling edge so wr_data_planes is stable when the write
    // controller captures the beat on the next posedge, then wait for the
    // controller to finish before the caller changes the data.
    @(negedge clk);
    addr = t_addr;
    wr_data = t_data;
    rq_wr = 1;
    rq_valid = 1;
    $write("SRAM WRITE @ %d, DATA: %d... ", t_addr, wr_data);
    @(posedge clk);
    @(negedge clk);
    rq_valid = 0;
    while (!rq_ready) @(negedge clk);
    $display("GD");
endtask

task sram_read(
    input logic [$clog2(numRows)-1:0] t_addr
);
    @(negedge clk);
    addr = t_addr;
    rq_wr = 0;
    rq_valid = 1;
    $write("SRAM READ @ %d,", t_addr);
    @(posedge clk);
    @(negedge clk);
    rq_valid = 0;
    $write("...");
    while (!rd_valid) @(negedge clk);
    $display("DATA: %d", rd_data);
endtask

task send_mac_request();
    // Drive on the falling edge so the posedge sample never races the file
    // read / partial mac_data update.
    @(negedge clk);
    mac_data_valid = 1;
    for (i = 0; i < numRows; i++) $fscanf(f_x, "%d", mac_data[i]);
    while (!ready_o) @(negedge clk); // Wait for request take
    @(negedge clk);
    mac_data_valid = 0;
endtask

task set_config();
    // Set config
    cfg.adc_ref_range_shifts = adcShift[3:0];
    cfg.binary_cfg = macMode;
    cfg.unsigned_acts = unsignedActs;
    cfg.n_input_bits_cfg = xBits;
    cfg.weight_bits_cfg = weightBits;
    cfg.weight_signed_cfg = weightSigned;
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
`ifndef SYNOPSYS
initial begin
    $dumpfile("tb_seq_acc.vcd");
    $dumpvars(0);
end
`endif

// File paths use relative paths from the simulation directory (sims/)
static string path = "../tb/seq_acc/inputs/";

initial begin

    test_phase = P_INIT;
    
    // Set config
    set_config();

    if (cfg.binary_cfg == 1) $display("MAC MODE: BINARY");
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
    f_wx = $fopen({path, "wx_clipped.txt"}, "r");
    if (f_wx == 0) begin
        $display("[TB ERROR] cannot open input file %s", {path, "wx_clipped.txt"});
        $fatal(1, "missing input file: generate it with pytest (see README) or provide it");
    end

    `ifdef AMS
        if (cfg.binary_cfg == 1) begin
            f_mac_out = $fopen({path, "mac_out_ams_binary.txt"}, "w");
            if (f_mac_out == 0) begin
                $display("[TB ERROR] cannot create output file %s", {path, "mac_out_ams_binary.txt"});
                $fatal(1, "cannot create output file");
            end
        end
        else begin
            f_mac_out = $fopen({path, "mac_out_ams_bipolar.txt"}, "w");
            if (f_mac_out == 0) begin
                $display("[TB ERROR] cannot create output file %s", {path, "mac_out_ams_bipolar.txt"});
                $fatal(1, "cannot create output file");
            end
        end
    `else
        if (cfg.binary_cfg == 1) begin
            f_mac_out = $fopen({path, "mac_out_rtl_binary.txt"}, "w");
            if (f_mac_out == 0) begin
                $display("[TB ERROR] cannot create output file %s", {path, "mac_out_rtl_binary.txt"});
                $fatal(1, "cannot create output file");
            end
        end
        else begin
            f_mac_out = $fopen({path, "mac_out_rtl_bipolar.txt"}, "w");
            if (f_mac_out == 0) begin
                $display("[TB ERROR] cannot create output file %s", {path, "mac_out_rtl_bipolar.txt"});
                $fatal(1, "cannot create output file");
            end
        end
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
        wr_data_planes = '0;
        if (weightPlanes) begin
            // One word per weight bit-plane: w.txt row i, plane p.
            for (int p = 0; p < numPlanes; p++) begin
                if ($fscanf(f_w, "%d", scan_data) != 1)
                    $fatal(1, "short w.txt (multibit mode)");
                wr_data_planes[p*numCols +: numCols] = scan_data;
            end
        end else begin
            if ($fscanf(f_w, "%d", scan_data) != 1)
                $fatal(1, "short w.txt");
            for (int p = 0; p < numPlanes; p++)
                wr_data_planes[p*numCols +: numCols] = scan_data;
        end
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
    if (streamMacs) begin
        @(negedge clk);
        mac_data_valid = 1;
        for (int h = 0; h < xBatches; h++) begin
            for (i = 0; i < numRows; i++) $fscanf(f_x, "%d", mac_data[i]);
            while (!ready_o) @(negedge clk);
            @(negedge clk);
        end
        mac_data_valid = 0;
    end else begin
        for (int h = 0; h < xBatches; h++) begin
            send_mac_request();
            // We do not need to read result here because it is
            // done by the always block somewhere above
        end
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
