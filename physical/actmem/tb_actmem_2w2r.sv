`timescale 1ns/1ps

module tb_actmem_2w2r;

    parameter int DEPTH = 256;
    parameter int MACRO_ROWS = 256;

    logic clk = 1'b0;
    logic nrst = 1'b0;

    logic wr_en_1;
    logic [31:0] wr_addr_1;
    logic [31:0] wr_data_1;
    logic rd_en_1;
    logic [31:0] rd_addr_1;
    logic [31:0] gold_rd_data_1;
    logic [31:0] dut_rd_data_1;

    logic wr_en_2;
    logic [31:0] wr_addr_2;
    logic [255:0] wr_data_2;
    logic rd_en_2;
    logic [31:0] rd_addr_2;
    logic [255:0] gold_rd_data_2;
    logic [255:0] dut_rd_data_2;

    always #5 clk = ~clk;

    ram_2w2r #(
        .addrWidth(32),
        .dataSize(8),
        .interfaceWidth1(32),
        .interfaceWidth2(256),
        .depth(DEPTH)
    ) u_gold (
        .clk(clk),
        .nrst(nrst),
        .wr_en_1_i(wr_en_1),
        .wr_addr_1_i(wr_addr_1),
        .wr_data_1_i(wr_data_1),
        .rd_en_1_i(rd_en_1),
        .rd_addr_1_i(rd_addr_1),
        .rd_data_1_o(gold_rd_data_1),
        .wr_en_2_i(wr_en_2),
        .wr_addr_2_i(wr_addr_2),
        .wr_data_2_i(wr_data_2),
        .rd_en_2_i(rd_en_2),
        .rd_addr_2_i(rd_addr_2),
        .rd_data_2_o(gold_rd_data_2)
    );

    actmem_2w2r_ihp #(
        .addrWidth(32),
        .dataSize(8),
        .interfaceWidth1(32),
        .interfaceWidth2(256),
        .depth(DEPTH),
        .MACRO_ROWS(MACRO_ROWS)
    ) u_dut (
        .clk(clk),
        .nrst(nrst),
        .wr_en_1_i(wr_en_1),
        .wr_addr_1_i(wr_addr_1),
        .wr_data_1_i(wr_data_1),
        .rd_en_1_i(rd_en_1),
        .rd_addr_1_i(rd_addr_1),
        .rd_data_1_o(dut_rd_data_1),
        .wr_en_2_i(wr_en_2),
        .wr_addr_2_i(wr_addr_2),
        .wr_data_2_i(wr_data_2),
        .rd_en_2_i(rd_en_2),
        .rd_addr_2_i(rd_addr_2),
        .rd_data_2_o(dut_rd_data_2)
    );

    function automatic [31:0] pattern1(input int unsigned base);
        pattern1 = 32'hC0DE_0000 ^ (base * 32'h0001_0001);
    endfunction

    function automatic [255:0] pattern2(input int unsigned base);
        for (int i = 0; i < 32; i++) begin
            pattern2[i*8 +: 8] = (base + i) & 8'hFF;
        end
    endfunction

    task automatic wr1(input int unsigned addr, input [31:0] data);
        @(negedge clk);
        wr_en_1 = 1'b1;
        wr_addr_1 = addr;
        wr_data_1 = data;
        @(posedge clk);
        @(negedge clk);
        wr_en_1 = 1'b0;
    endtask

    task automatic rd1(input int unsigned addr, output [31:0] gold, output [31:0] dut);
        @(negedge clk);
        rd_en_1 = 1'b1;
        rd_addr_1 = addr;
        @(posedge clk);
        @(negedge clk);
        rd_en_1 = 1'b0;
        gold = gold_rd_data_1;
        dut = dut_rd_data_1;
    endtask

    task automatic wr2(input int unsigned addr, input [255:0] data);
        @(negedge clk);
        wr_en_2 = 1'b1;
        wr_addr_2 = addr;
        wr_data_2 = data;
        @(posedge clk);
        @(negedge clk);
        wr_en_2 = 1'b0;
    endtask

    task automatic rd2(input int unsigned addr, output [255:0] gold, output [255:0] dut);
        @(negedge clk);
        rd_en_2 = 1'b1;
        rd_addr_2 = addr;
        @(posedge clk);
        @(negedge clk);
        rd_en_2 = 1'b0;
        gold = gold_rd_data_2;
        dut = dut_rd_data_2;
    endtask

    task automatic check1(input int unsigned addr);
        logic [31:0] gold, dut;
        rd1(addr, gold, dut);
        if (gold !== dut) begin
            $fatal(1, "port1 mismatch at %0d: gold=%08x dut=%08x", addr, gold, dut);
        end
    endtask

    task automatic check2(input int unsigned addr);
        logic [255:0] gold, dut;
        rd2(addr, gold, dut);
        if (gold !== dut) begin
            $fatal(1, "port2 mismatch at %0d: gold=%064x dut=%064x", addr, gold, dut);
        end
    endtask

    initial begin
        wr_en_1 = 1'b0;
        wr_addr_1 = '0;
        wr_data_1 = '0;
        rd_en_1 = 1'b0;
        rd_addr_1 = '0;

        wr_en_2 = 1'b0;
        wr_addr_2 = '0;
        wr_data_2 = '0;
        rd_en_2 = 1'b0;
        rd_addr_2 = '0;

        repeat (3) @(negedge clk);
        nrst = 1'b1;
        repeat (2) @(negedge clk);

        if (dut_rd_data_1 !== 32'b0 || dut_rd_data_2 !== 256'b0) begin
            $fatal(1, "reset output is not zero");
        end

        // Internal port: every 256-bit word.
        for (int a = 0; a < DEPTH; a += 32) begin
            wr2(a, pattern2(a));
        end
        for (int a = 0; a < DEPTH; a += 32) begin
            check2(a);
        end

        // External port: every 32-bit word.
        for (int a = 0; a < DEPTH; a += 4) begin
            wr1(a, pattern1(a));
        end
        for (int a = 0; a < DEPTH; a += 4) begin
            check1(a);
        end

        // Cross-port checks (also verify the golden byte-order quirk).
        for (int a = 0; a < DEPTH; a += 32) begin
            wr2(a, pattern2(a + 1));
            for (int k = 0; k < 32; k += 4) begin
                check1(a + k);
            end
        end
        for (int a = 0; a < DEPTH; a += 32) begin
            for (int k = 0; k < 32; k += 4) begin
                wr1(a + k, pattern1(a + k + 7));
            end
            check2(a);
        end

        // Wide accesses starting at a 4-byte (not 32-byte) boundary.
        for (int a = 4; a + 31 < DEPTH; a += 8) begin
            wr2(a, pattern2(a + 3));
            check2(a);
        end

        // Simultaneous internal read and write to different rows.
        wr2(0, pattern2(32'h100));
        wr2(32, pattern2(32'h200));
        @(negedge clk);
        wr_en_2 = 1'b1;
        wr_addr_2 = 0;
        wr_data_2 = pattern2(32'h300);
        rd_en_2 = 1'b1;
        rd_addr_2 = 32;
        @(posedge clk);
        @(negedge clk);
        wr_en_2 = 1'b0;
        rd_en_2 = 1'b0;
        if (gold_rd_data_2 !== dut_rd_data_2) begin
            $fatal(1, "simultaneous read/write mismatch: gold=%064x dut=%064x",
                   gold_rd_data_2, dut_rd_data_2);
        end

        // Same-row internal read/write: the macro has no conflict handling.
        wr2(0, pattern2(32'h400));
        @(negedge clk);
        wr_en_2 = 1'b1;
        wr_addr_2 = 0;
        wr_data_2 = pattern2(32'h500);
        rd_en_2 = 1'b1;
        rd_addr_2 = 0;
        @(posedge clk);
        @(negedge clk);
        wr_en_2 = 1'b0;
        rd_en_2 = 1'b0;
        if (gold_rd_data_2 !== dut_rd_data_2) begin
            $fatal(1, "same-address read/write mismatch: gold=%064x dut=%064x",
                   gold_rd_data_2, dut_rd_data_2);
        end

        wr2(0, pattern2(32'h600));
        @(negedge clk);
        wr_en_2 = 1'b1;
        wr_addr_2 = 0;
        wr_data_2 = pattern2(32'h700);
        rd_en_2 = 1'b1;
        rd_addr_2 = 4;
        @(posedge clk);
        @(negedge clk);
        wr_en_2 = 1'b0;
        rd_en_2 = 1'b0;
        if (gold_rd_data_2 !== dut_rd_data_2) begin
            $fatal(1, "same-row read/write mismatch: gold=%064x dut=%064x",
                   gold_rd_data_2, dut_rd_data_2);
        end

        $display("ACTMEM 2W2R IHP wrapper PASS (depth=%0d)", DEPTH);
        $finish;
    end

endmodule
