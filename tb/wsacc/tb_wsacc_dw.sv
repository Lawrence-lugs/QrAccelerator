`timescale 1ns/1ps

module tb_wsacc_dw #(
    parameter int numPes = 4,
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

    int fail_count = 0;
    int first_done_beat = -1;

    // signed int8 weights, two's-complement byte patterns + signed value
    logic [7:0] w_pat [numPes-1:0][windowElements-1:0];
    logic signed [dataWidth-1:0] w_signed [numPes-1:0][windowElements-1:0];
    logic [dataWidth-1:0] act [numPes-1:0][windowElements-1:0];
    logic signed [outputWidth-1:0] golden [numPes-1:0];

    initial begin
        clk = 0;
        // ---------------- weights (signed int8) ----------------
        // PE0
        w_pat[0][0] = 8'h80; w_signed[0][0] = -128;
        w_pat[0][1] = 8'hff; w_signed[0][1] = -1;
        w_pat[0][2] = 8'h00; w_signed[0][2] = 0;
        w_pat[0][3] = 8'h01; w_signed[0][3] = 1;
        w_pat[0][4] = 8'h7f; w_signed[0][4] = 127;
        w_pat[0][5] = 8'h81; w_signed[0][5] = -127;
        w_pat[0][6] = 8'h00; w_signed[0][6] = 0;
        w_pat[0][7] = 8'hff; w_signed[0][7] = -1;
        w_pat[0][8] = 8'h01; w_signed[0][8] = 1;
        // PE1
        w_pat[1][0] = 8'h7f; w_signed[1][0] = 127;
        w_pat[1][1] = 8'h00; w_signed[1][1] = 0;
        w_pat[1][2] = 8'hff; w_signed[1][2] = -1;
        w_pat[1][3] = 8'h80; w_signed[1][3] = -128;
        w_pat[1][4] = 8'h01; w_signed[1][4] = 1;
        w_pat[1][5] = 8'h00; w_signed[1][5] = 0;
        w_pat[1][6] = 8'h7f; w_signed[1][6] = 127;
        w_pat[1][7] = 8'h81; w_signed[1][7] = -127;
        w_pat[1][8] = 8'hff; w_signed[1][8] = -1;
        // PE2
        w_pat[2][0] = 8'hff; w_signed[2][0] = -1;
        w_pat[2][1] = 8'h7f; w_signed[2][1] = 127;
        w_pat[2][2] = 8'h80; w_signed[2][2] = -128;
        w_pat[2][3] = 8'h01; w_signed[2][3] = 1;
        w_pat[2][4] = 8'h00; w_signed[2][4] = 0;
        w_pat[2][5] = 8'hff; w_signed[2][5] = -1;
        w_pat[2][6] = 8'h01; w_signed[2][6] = 1;
        w_pat[2][7] = 8'h00; w_signed[2][7] = 0;
        w_pat[2][8] = 8'h7f; w_signed[2][8] = 127;
        // PE3
        w_pat[3][0] = 8'h00; w_signed[3][0] = 0;
        w_pat[3][1] = 8'h81; w_signed[3][1] = -127;
        w_pat[3][2] = 8'h01; w_signed[3][2] = 1;
        w_pat[3][3] = 8'h7f; w_signed[3][3] = 127;
        w_pat[3][4] = 8'h80; w_signed[3][4] = -128;
        w_pat[3][5] = 8'h01; w_signed[3][5] = 1;
        w_pat[3][6] = 8'hff; w_signed[3][6] = -1;
        w_pat[3][7] = 8'h00; w_signed[3][7] = 0;
        w_pat[3][8] = 8'hff; w_signed[3][8] = -1;

        // ---------------- activations (unsigned 0..255, small range) ----------------
        act[0][0]=10; act[0][1]=15; act[0][2]=5;  act[0][3]=20; act[0][4]=0;  act[0][5]=12; act[0][6]=3;  act[0][7]=1;  act[0][8]=8;
        act[1][0]=20; act[1][1]=0;  act[1][2]=12; act[1][3]=8;  act[1][4]=15; act[1][5]=7;  act[1][6]=20; act[1][7]=10; act[1][8]=3;
        act[2][0]=1;  act[2][1]=2;  act[2][2]=3;  act[2][3]=4;  act[2][4]=5;  act[2][5]=6;  act[2][6]=7;  act[2][7]=8;  act[2][8]=9;
        act[3][0]=15; act[3][1]=14; act[3][2]=13; act[3][3]=12; act[3][4]=11; act[3][5]=10; act[3][6]=9;  act[3][7]=8;  act[3][8]=7;

        // ---------------- golden (signed int8 weight * unsigned activation) ----------------
        for (int c = 0; c < numPes; c++) begin
            golden[c] = 0;
            for (int t = 0; t < windowElements; t++) begin
                golden[c] += w_signed[c][t] * $signed({1'b0, act[c][t]});
            end
        end

        // ---------------- reset ----------------
        nrst = 0;
        data_i_valid = 0;
        weight_itf_i_valid = 0;
        data_o_ready = 1;
        data_i = '0;
        weight_itf_i = '0;
        #(CLK_PERIOD * 2);
        nrst = 1;
        #(CLK_PERIOD * 2);

        // ---------------- load weights: one beat per tap, weight_addr 0..8 ----------------
        // byte c of the 32-bit word goes to PE c (matches kernel_to_writes: ch0/PE0 in byte0/LSB)
        // Drive enough beats to distinguish numPes=4 (done@beat8) vs numPes=32 (done@beat71) vs capture-fail (never).
        weight_itf_i_valid = 1;
        for (int t = 0; t < 80; t++) begin
            weight_itf_i = { w_pat[3][t % windowElements], w_pat[2][t % windowElements],
                             w_pat[1][t % windowElements], w_pat[0][t % windowElements] };
            #5;          // posedge: DUT captures the beat
            #1;          // let weight_writing_done update
            if (weight_writing_done === 1'b1 && first_done_beat < 0) first_done_beat = t;
            #4;          // back to negedge for the next beat
        end
        weight_itf_i_valid = 0;

        $display("DEBUG: first_done_beat=%0d (expect 8 for numPes=4, 71 for numPes=32, -1 = capture fail)", first_done_beat);

        if (first_done_beat < 0) begin
            $display("ERROR: weight_writing_done never asserted in 80 beats (input capture fail)");
            fail_count++;
        end else begin
            $display("INFO: weight_writing_done first asserted at beat %0d", first_done_beat);
        end

        // ---------------- drive activations ----------------
        for (int c = 0; c < numPes; c++) begin
            for (int t = 0; t < windowElements; t++) begin
                data_i[c][t] = act[c][t];
            end
        end
        data_i_valid = 1;
        #5;          // posedge: DUT captures data_i and sets data_o_valid
        #1;          // let data_o_valid update
        data_i_valid = 0;

        // ---------------- capture and compare outputs ----------------
        if (data_o_valid !== 1'b1) begin
            $display("ERROR: data_o_valid not asserted");
            fail_count++;
        end

        for (int c = 0; c < numPes; c++) begin
            logic signed [outputWidth-1:0] got;
            got = $signed(data_o[c]);
            $display("PE%0d: data_o=%0d (0x%04h) golden=%0d", c, got, data_o[c], golden[c]);
            if (got !== golden[c]) begin
                $display("MISMATCH PE%0d: got=%0d golden=%0d", c, got, golden[c]);
                fail_count++;
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
