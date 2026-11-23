`timescale 1ns/1ps

import qracc_pkg::*;

// Bit-exact write-path testbench for wr_controller.
// Splits a write beat into 1, 2 or 4 consecutive rows (wr_bus_sel 0/1/2) and
// verifies the wordline sequence, per-row write data and the done pulse.
module tb_wr_path #(
    parameter int numRows = 128,
    parameter int numCols = 32,
    parameter int numBeatRows = 4,
    parameter int wrBusSel = 0
) (
);
    localparam int BEAT_BITS = numBeatRows * numCols;
    localparam int CLK_PERIOD = 20;

    logic clk;
    logic nrst;

    logic write_i;
    logic read_i;
    logic [1:0] wr_bus_sel_i;
    logic [$clog2(numRows)-1:0] addr_i;
    logic [BEAT_BITS-1:0] wr_data_i;

    logic done;
    logic ready;
    logic [numCols-1:0] wr_data_q;

    logic [numCols-1:0] c3sram_csel_o;
    logic c3sram_saen_o;
    logic c3sram_w2b_o;
    logic c3sram_nprecharge_o;
    logic [numRows-1:0] c3sram_wl_o;

    wr_controller #(
        .numRows(numRows),
        .numCols(numCols),
        .numBeatRows(numBeatRows)
    ) dut (
        .clk(clk),
        .nrst(nrst),
        .write_i(write_i),
        .read_i(read_i),
        .wr_bus_sel_i(wr_bus_sel_i),
        .addr_i(addr_i),
        .wr_data_i(wr_data_i),
        .done(done),
        .ready(ready),
        .wr_data_q(wr_data_q),
        .c3sram_csel_o(c3sram_csel_o),
        .c3sram_saen_o(c3sram_saen_o),
        .c3sram_w2b_o(c3sram_w2b_o),
        .c3sram_nprecharge_o(c3sram_nprecharge_o),
        .c3sram_wl_o(c3sram_wl_o)
    );

    int fail_count = 0;

    // Collected one-hot wordline row addresses (w2b && one-hot wl), deduped per row.
    int row_log [numBeatRows];
    logic [numCols-1:0] wd_log [numBeatRows];
    int row_log_count;

    function int wrl_onehot_index(input logic [numRows-1:0] wl);
        int cnt, idx;
        begin
            cnt = 0;
            idx = -1;
            for (int i = 0; i < numRows; i++) begin
                if (wl[i]) begin
                    cnt = cnt + 1;
                    idx = i;
                end
            end
            if (cnt == 1)
                wrl_onehot_index = idx;
            else
                wrl_onehot_index = -1;
        end
    endfunction

    // Monitor: on each posedge, record the current row when w2b is high and
    // the wordline is one-hot. Dedupe consecutive repeats (two cycles per row).
    always @(posedge clk) begin
        if (c3sram_w2b_o) begin
            int idx;
            idx = wrl_onehot_index(c3sram_wl_o);
            if (idx >= 0 && (row_log_count == 0 || row_log[row_log_count-1] != idx)) begin
                row_log[row_log_count] = idx;
                wd_log[row_log_count] = wr_data_q;
                row_log_count = row_log_count + 1;
            end
        end
    end

    task automatic run_beat(
        input logic [$clog2(numRows)-1:0] t_addr,
        input logic [BEAT_BITS-1:0] t_beat
    );
        int rpb;
        int k;
        begin
            rpb = (wr_bus_sel_i == 2'd1) ? 2 : (wr_bus_sel_i == 2'd2) ? 4 : 1;

            // Reset per-beat collection.
            row_log_count = 0;

            // Drive the write request.
            addr_i = t_addr;
            wr_data_i = t_beat;
            wr_bus_sel_i = wrBusSel;
            write_i = 1;
            read_i = 0;
            @(posedge clk);
            write_i = 0;
            read_i = 0;

            // Wait for done (single-cycle pulse asserted after the last row).
            // done is combinational and stable during its cycle; catch the rising
            // edge to avoid sampling races at the clk posedge.
            @(posedge done);
            #1;
            if (!done) begin
                $display("MISMATCH: addr=%0d rpb=%0d done not asserted", t_addr, rpb);
                fail_count = fail_count + 1;
            end
            // Wait for done to deassert.
            while (done) @(posedge clk);

            // (a) row addresses in order addr, addr+1, ... ; count == rows_per_beat.
            if (row_log_count != rpb) begin
                $display("MISMATCH: addr=%0d rpb=%0d row_log_count=%0d (expected %0d)",
                         t_addr, rpb, row_log_count, rpb);
                fail_count = fail_count + 1;
            end else begin
                for (k = 0; k < rpb; k = k + 1) begin
                    if (row_log[k] != t_addr + k) begin
                        $display("MISMATCH: addr=%0d k=%0d row_log=%0d expected=%0d",
                                 t_addr, k, row_log[k], t_addr + k);
                        fail_count = fail_count + 1;
                    end
                    // (b) per-row write data equals the expected slice.
                    if (wd_log[k] !== t_beat[k*numCols +: numCols]) begin
                        $display("MISMATCH: addr=%0d k=%0d wr_data_q=%0d expected_slice=%0d",
                                 t_addr, k, wd_log[k], t_beat[k*numCols +: numCols]);
                        fail_count = fail_count + 1;
                    end
                end
            end

            @(posedge clk);
        end
    endtask

    initial begin
        logic [BEAT_BITS-1:0] beats [4];
        logic [$clog2(numRows)-1:0] addrs [4];
        int seed;
        int b;

        addrs[0] = 0;
        addrs[1] = 4;
        addrs[2] = 8;
        addrs[3] = 124;

        seed = 32'h12345678;
        for (b = 0; b < 4; b = b + 1) begin
            beats[b] = { $urandom(seed), $urandom(seed), $urandom(seed), $urandom(seed) };
        end

        nrst = 0;
        clk = 0;
        write_i = 0;
        read_i = 0;
        wr_bus_sel_i = wrBusSel;
        addr_i = 0;
        wr_data_i = 0;

        #(CLK_PERIOD * 2);
        nrst = 1;
        #(CLK_PERIOD * 2);

        // Wait for ready.
        while (!ready) @(posedge clk);
        @(posedge clk);

        for (b = 0; b < 4; b = b + 1) begin
            run_beat(addrs[b], beats[b]);
        end

        #(CLK_PERIOD * 4);

        if (fail_count == 0) begin
            $display("TB_PASS");
        end else begin
            $display("TB_FAIL");
            $fatal(1, "Testbench failed with %0d mismatches", fail_count);
        end

        $finish();
    end

    // Clock generation
    always #(CLK_PERIOD / 2) clk = ~clk;

    // Watchdog
    initial begin
        #(CLK_PERIOD * 50000);
        $display("WATCHDOG TIMED OUT");
        $finish();
    end

endmodule
