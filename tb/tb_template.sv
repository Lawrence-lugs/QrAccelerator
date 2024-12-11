`timescale 1ns/1ps

module tb_template;


// replace with your desired clk period
parameter int unsigned CLK_PERIOD=20;

logic clk,nrst;

// add pins
template UUT(
    .clk(clk),
    .nrst(nrst),

);

// add tb variables

always 
    #(CLK_PERIOD/2) clk = ~clk;

initial begin
    $vcdplusfile("out.vpd");
    $vcdpluson;

    $display("======");

    clk = 0;
    nrst = 0;
    #(CLK_PERIOD*5)
    nrst = 1;


    // Your code


    $display("done.");
    $display("======");
end

endmodule