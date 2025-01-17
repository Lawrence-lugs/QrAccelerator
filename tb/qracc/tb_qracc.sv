//Verilog HDL for "test_caps", "tb_q_redis", "systemVerilog"

`timescale 1ns/1ps

module tb_qracc #(
    parameter SRAM_ROWS = 128,
    parameter SRAM_COLS = 32,
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

logic [numRows-1:0] vdr_sel_int;
logic [numRows-1:0] vdr_selb_int;
logic [numRows-1:0] vss_sel_int;
logic [numRows-1:0] vss_selb_int;
logic [numRows-1:0] vrst_sel_int;
logic [numRows-1:0] vrst_selb_int;
logic [numRows-1:0] wl_int;
logic [numCols-1:0] sa_out_int;
logic pch_int;
logic [numCols-1:0] wr_data_int;
logic write_int;
logic [numCols-1:0] csel_int;
logic saen_int;
logic [numCols*compCount-1:0] adc_out_int;
logic nf_int;
logic nfb_int;
logic m2a_int;
logic m2ab_int;
logic r2a_int;
logic r2ab_int;

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

logic mac_en;
logic rq_wr;
logic rq_valid;
logic rq_ready;
logic rd_valid;
logic [numCols-1:0] rd_data;
logic [numCols-1:0] wr_data;
logic [$clog2(numRows)-1:0] addr;

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
    .n_input_bits_cfg(n_input_bits_cfg),
    .n_adc_bits_cfg(n_adc_bits_cfg),
    .binary_cfg(mode_cfg),
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

ts_qracc #(
    .numRows(SRAM_ROWS),
    .numCols(SRAM_COLS),
    .numAdcBits(numAdcBits)
) u_ts_qracc (
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

twos_to_bipolar #(
    .inBits(2),
    .numLanes(numRows)
) u_twos_to_bipolar (
    .twos(x_data),
    .bipolar_p(data_p_i),
    .bipolar_n(data_n_i)
);

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

    mode_cfg = 0;

    // Open files        
    f_w = $fopen({path, "w.txt"}, "r");
    f_x = $fopen({path, "x.txt"}, "r");
    f_wx = $fopen({path, "wx_4b.txt"}, "r");
    f_adc_out = $fopen({path, "adc_out.txt"}, "w");

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
    // for(int j = 0; j < numRows; j++) begin
    //     $display("X[%d] = %d,(%d,%d)", j, $signed(x_data[j]), data_p_i[j], data_n_i[j]);
    // end

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
