//Verilog HDL for "test_caps", "tb_q_redis", "systemVerilog"a aa

`timescale 1ns/1ps

module tb_q_redis #(
    parameter SRAM_ROWS = 128
) ( 
    output reg [SRAM_ROWS-1:0] VDR_SEL,
    output reg [SRAM_ROWS-1:0] VSS_SEL,    
    output reg [SRAM_ROWS-1:0] VDR_SELB,
    output reg [SRAM_ROWS-1:0] VSS_SELB,   
    output reg [SRAM_ROWS-1:0] VRST_SEL,
    output reg [SRAM_ROWS-1:0] VRST_SELB,
    output logic NF,
    output logic NFB,
    output logic M2A,
    output logic M2AB,
    output logic R2A,
    output logic R2AB,
    output logic PCH,
    output logic WR_DATA,
    output logic WRITE,
    output logic CSEL,
    output logic SAEN,
    output logic CLK, CLKB
);

localparam CLK_PERIOD = 20;
integer i;

reg [SRAM_ROWS-1:0] data;

always @(*) begin
    if (CLK) begin
        VDR_SEL = 0;
        VSS_SEL = 0;
    end else begin
        VDR_SEL = data;
        VSS_SEL = ~data;
    end
    // B is always flip
    VDR_SELB = ~VDR_SEL;
    VSS_SELB = ~VSS_SEL;
end

// Clock Generation
initial begin
    CLK = 0;
    forever begin
        #(CLK_PERIOD/2);
        CLK = 0;
        #(CLK_PERIOD/2);
        CLK = 1;
    end
end
always_comb begin
    CLKB = ~CLK;
end

// VCD generation
initial begin
    $dumpfile("res.vcd");
    $dumpvars();
end

initial begin
    data = 0;
    #(CLK_PERIOD*5); // Allow initial voltage transients to settle
    
    for (int i = 0; i < SRAM_ROWS-1; i++) begin
        data = {data[126:0], 1'b1};
        #(CLK_PERIOD);
    end

    #(CLK_PERIOD*2);

    $display("TEST SUCCESS");

    $finish();
end

endmodule
