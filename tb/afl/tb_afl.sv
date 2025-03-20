`timescale 1ns/1ps

module tb_afl #(

) (

);

/////////////
// PARAMETERS
/////////////

parameter CLK_PERIOD    = 20    ;
parameter aflDimY       = 128   ;
parameter aflDimX       = 6     ;
parameter inputWidth    = 32    ;
parameter elementWidth  = 4     ;
parameter addrWidth     = 32    ; // Minimum $clog2(aflDimY/inputElements)
localparam inputElements = inputWidth/elementWidth;

/////////////
// SIGNALS
/////////////

logic clk, nrst;

logic [inputWidth-1:0] afl_data_i;
logic afl_wr_data_valid;
logic [addrWidth-1:0] input_addr_offset;
logic [aflDimY-1:0][elementWidth-1:0] afl_data_o;
logic [aflDimX-1:0][aflDimY-1:0][1:0] ctrl_load_direction_i;

//////////////////////
// MODULE INSTANTIATION
//////////////////////

aligned_feature_loader #(
    .aflDimY                    (aflDimY),
    .aflDimX                    (aflDimX),
    .inputWidth                 (inputWidth),
    .elementWidth               (elementWidth),
    .addrWidth                  (addrWidth)
) u_afl (
    .clk                        (clk),
    .nrst                       (nrst),
    .data_i                     (afl_data_i),
    .valid_i                    (afl_wr_data_valid),
    .input_addr_offset          (input_addr_offset),
    .data_o                     (afl_data_o),
    .ctrl_load_direction_i      (ctrl_load_direction_i)
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

initial begin
    
    #(CLK_PERIOD*2);
    nrst = 1;
    #(CLK_PERIOD*2);

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