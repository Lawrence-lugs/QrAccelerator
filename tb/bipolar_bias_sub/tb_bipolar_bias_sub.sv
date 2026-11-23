// Unit test for bipolar_bias_sub.
//
// Reads A_j popcounts from inputs/a.txt (one trial per line, inputTrits
// columns), drives the module with the same accept/stage timing as seq_acc and
// writes the bias at valid_o to outputs/bias_rtl.txt.
`timescale 1ns/1ps

module tb_bipolar_bias_sub #(
    parameter int inputTrits = 7,
    parameter int numTrials = 32,
    parameter int accumulatorBits = 16
) ();

    localparam int CLK_PERIOD = 20;

    logic clk;
    logic nrst;
    logic mac_valid;
    logic [3:0] input_trits_i;
    logic [31:0] popcount_i;
    logic valid_o;
    logic signed [accumulatorBits-1:0] bias_o;

    int f_in, f_out;
    int scan;
    int a_vals[0:63];

    bipolar_bias_sub #(
        .maxInputTrits(inputTrits),
        .accumulatorBits(accumulatorBits)
    ) u_bias (
        .clk(clk),
        .nrst(nrst),
        .bias_enable(1'b1),
        .input_trits_i(input_trits_i),
        .mac_valid(mac_valid),
        .popcount_i(popcount_i),
        .valid_o(valid_o),
        .bias_o(bias_o)
    );

    always #(CLK_PERIOD/2) clk = ~clk;
    initial clk = 0;

    initial begin
        nrst = 0;
        mac_valid = 0;
        popcount_i = 0;
        input_trits_i = inputTrits[3:0];

        f_in = $fopen("../tb/bipolar_bias_sub/inputs/a.txt", "r");
        if (f_in == 0) $fatal(1, "missing inputs/a.txt");
        f_out = $fopen("../tb/bipolar_bias_sub/outputs/bias_rtl.txt", "w");
        if (f_out == 0) $fatal(1, "cannot open outputs/bias_rtl.txt");

        #(CLK_PERIOD * 2);
        nrst = 1;
        #(CLK_PERIOD * 2);

        for (int t = 0; t < numTrials; t++) begin
            for (int j = 0; j < inputTrits; j++) begin
                if ($fscanf(f_in, "%d", scan) != 1) $fatal(1, "short a.txt");
                a_vals[j] = scan;
            end

            // Accept a word, then present A_0 .. A_(T-1) on consecutive cycles.
            @(negedge clk); mac_valid = 1;
            @(negedge clk); mac_valid = 0;
            for (int j = 0; j < inputTrits; j++) begin
                @(negedge clk);
                popcount_i = a_vals[j];
            end

            // valid_o is asserted in the cycle after the final shift-add stage.
            while (!valid_o) @(negedge clk);
            $fwrite(f_out, "%0d\n", $signed(bias_o));

            // Let valid_o fall before the next trial.
            @(negedge clk);
            while (valid_o) @(negedge clk);
        end

        $fclose(f_out);
        $display("TEST SUCCESS");
        $finish();
    end

    initial begin
        #(CLK_PERIOD * 200000);
        $display("ERROR: WATCHDOG TIMED OUT");
        $finish();
    end

endmodule
