`timescale 1ns/1ps

module tb_wsacc_dw32 #(
    parameter int numPes = 32,
    parameter int windowElements = 9,
    parameter int dataWidth = 8,
    parameter int outputWidth = 16,
    parameter int weightInterfaceWidth = 32
) (
);
    logic clk;
    logic nrst;

    logic [numPes-1:0][windowElements-1:0][dataWidth-1:0] data_i;
    logic data_i_valid;
    logic data_i_ready;
    logic [weightInterfaceWidth-1:0] weight_itf_i;
    logic weight_itf_i_valid;
    logic weight_writing_done;
    logic [numPes-1:0][outputWidth-1:0] data_o;
    logic data_o_valid;
    logic data_o_ready;

    wsacc_pe_cluster #(
        .numPes(numPes),
        .windowElements(windowElements),
        .outputWidth(outputWidth),
        .weightInterfaceWidth(weightInterfaceWidth)
    ) dut (
        .clk(clk),
        .nrst(nrst),
        .data_i(data_i),
        .data_i_valid(data_i_valid),
        .data_i_ready(data_i_ready),
        .weight_itf_i(weight_itf_i),
        .weight_itf_i_valid(weight_itf_i_valid),
        .weight_writing_done(weight_writing_done),
        .data_o(data_o),
        .data_o_valid(data_o_valid),
        .data_o_ready(data_o_ready)
    );

    // clock
    localparam int CLK_PERIOD = 10;
    always #(CLK_PERIOD / 2) clk = ~clk;

    // 9 taps x 8 words (32 PEs / 4 bytes per word) = 72 weight words
    localparam int NUM_WEIGHT_WORDS = 72;
    // 4 window positions x 32 PEs x 9 taps = 1152 data entries
    localparam int NUM_POSITIONS = 4;
    localparam int DATA_ENTRIES = NUM_POSITIONS * numPes * windowElements;
    localparam int GOLDEN_ENTRIES = NUM_POSITIONS * numPes;

    logic [weightInterfaceWidth-1:0] weight_mem [0:NUM_WEIGHT_WORDS-1];
    logic [dataWidth-1:0]            data_mem   [0:DATA_ENTRIES-1];
    logic [outputWidth-1:0]          golden_mem [0:GOLDEN_ENTRIES-1];

    int fail_count = 0;
    int first_done_beat = -1;
    logic signed [outputWidth-1:0] got;
    logic signed [outputWidth-1:0] exp;
    logic signed [outputWidth-1:0] got_u;
    logic [7:0] wbyte;

    initial begin
        $readmemh("p9_dw_words.txt", weight_mem);
        $readmemh("dw_data_i.txt", data_mem);
        $readmemh("dw_golden.txt", golden_mem);

        clk = 0;
        nrst = 0;
        data_i_valid = 0;
        weight_itf_i_valid = 0;
        data_o_ready = 1;
        data_i = '0;
        weight_itf_i = '0;
        #(CLK_PERIOD * 2);
        nrst = 1;
        #(CLK_PERIOD * 2);

        // ---------------- load weights: 72 beats ----------------
        // beat b drives write_array[b] = word for tap = b/8, write_set = b%8.
        // RTL: tap=weight_addr, PE(4*write_set+i) <= byte i of weight_itf_i.
        // kernel_to_writes word[tap][word_in_tap] packs channels
        //   [4*word_in_tap .. 4*word_in_tap+3] with byte i (LSB i=0) = channel 4*word_in_tap+i,
        //   so PE c receives byte (c%4) of word (tap*8 + c/4) = channel c. Byte/PE mapping matches.
        weight_itf_i_valid = 1;
        for (int b = 0; b < NUM_WEIGHT_WORDS; b++) begin
            weight_itf_i = weight_mem[b];
            #5;          // posedge: DUT captures the beat
            #1;          // let weight_writing_done update
            if (weight_writing_done === 1'b1 && first_done_beat < 0) first_done_beat = b;
            #4;          // back to negedge for the next beat
        end
        weight_itf_i_valid = 0;

        $display("DEBUG: first_done_beat=%0d (expect 71 for numPes=32, -1 = capture fail)", first_done_beat);
        if (first_done_beat < 0) begin
            $display("ERROR: weight_writing_done never asserted in 72 beats (input capture fail)");
            fail_count++;
        end

        #(CLK_PERIOD * 2);

        // ---------------- drive 4 window positions and compare ----------------
        // Drive data_i, assert data_i_valid across a posedge so the cluster
        // captures the window and updates data_o, then compare.  Use explicit
        // clock-edge waits so each position is captured at a known posedge
        // (avoids phase drift across multiple positions).
        for (int p = 0; p < NUM_POSITIONS; p++) begin
            for (int c = 0; c < numPes; c++) begin
                for (int t = 0; t < windowElements; t++) begin
                    data_i[c][t] = data_mem[p * numPes * windowElements + c * windowElements + t];
                end
            end
            @(negedge clk);
            data_i_valid = 1;
            @(posedge clk);    // DUT captures data_i and updates data_o
            #1;
            data_i_valid = 0;

            if (data_o_valid !== 1'b1) begin
                $display("ERROR: position %0d: data_o_valid not asserted", p);
                fail_count++;
            end

            for (int c = 0; c < numPes; c++) begin
                got = $signed(data_o[c]);
                exp = $signed(golden_mem[p * numPes + c]);
                $display("POS%0d PE%0d: data_o=%0d (0x%04h) golden=%0d", p, c, got, data_o[c], exp);
                if (got !== exp) begin
                    $display("MISMATCH POS%0d PE%0d: got=%0d golden=%0d", p, c, got, exp);
                    // Diagnose weight encoding: golden with weights read as UNSIGNED.
                    got_u = 0;
                    for (int t = 0; t < windowElements; t++) begin
                        int word_idx = t * 8 + (c / 4);
                        int byte_idx = c % 4;
                        wbyte = weight_mem[word_idx][byte_idx * 8 +: 8];
                        got_u += $signed({1'b0, wbyte}) * $signed({1'b0, data_i[c][t]});
                    end
                    $display("DIAG POS%0d PE%0d: unsigned-weight golden=%0d  (got==unsigned? %0b)", p, c, got_u, (got === got_u));
                    fail_count++;
                end
            end
        end

        if (fail_count == 0) begin
            $display("TB_PASS");
        end else begin
            $display("TB_FAIL");
            $fatal(1, "Testbench failed with %0d mismatches", fail_count);
        end
        $finish();
    end
endmodule
