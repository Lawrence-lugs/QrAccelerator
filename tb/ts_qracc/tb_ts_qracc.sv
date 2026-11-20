// Unit test for the ts_qracc flash-ADC model.
//
// Sweeps every (ladder, s, mbl) on a single column and prints the code and the
// thermometer-decoded code.  pytest compares the log against
// qracc_marp.quantization.quant.adc_quantize (bit-exact).
//
// The SRAM is filled with ones, so mbl = |PSM_VDR| - |PSM_VSS| directly.
`timescale 1ns/1ps

import qracc_pkg::*;

module tb_ts_qracc #(
    parameter SRAM_ROWS = 64,
    parameter SRAM_COLS = 1,
    parameter numAdcBits = 4,
    parameter int adcFullScale = (1 << numAdcBits)
) ();

    localparam int numRows = SRAM_ROWS;
    localparam int numCols = SRAM_COLS;
    localparam int compCount = (2 ** numAdcBits) - 1;
    localparam int CLK_PERIOD = 20;
    localparam int adcMid = 1 << (numAdcBits - 1);

    logic clk;
    logic nrst;

    logic [3:0] adc_ref_range_shifts;
    logic binary_cfg;

    logic [numRows-1:0] PSM_VDR_SEL, PSM_VDR_SELB;
    logic [numRows-1:0] PSM_VSS_SEL, PSM_VSS_SELB;
    logic [numRows-1:0] PSM_VRST_SEL, PSM_VRST_SELB;
    logic [numRows-1:0] NSM_VDR_SEL, NSM_VDR_SELB;
    logic [numRows-1:0] NSM_VSS_SEL, NSM_VSS_SELB;
    logic [numRows-1:0] NSM_VRST_SEL, NSM_VRST_SELB;

    logic [numCols-1:0] SA_OUT;
    logic [numRows-1:0] WL;
    logic PCH;
    logic [numCols-1:0] WR_DATA;
    logic WRITE;
    logic [numCols-1:0] CSEL;
    logic SAEN;

    logic [compCount*numCols-1:0] ADC_OUT;
    logic signed [numCols-1:0][qrAccAdcCodeBits-1:0] ADC_CODE;

    logic NF, NFB, M2A, M2AB, R2A, R2AB;

    logic [compCount-1:0] therm_col;
    int decoded;

    assign therm_col = ADC_OUT[0 +: compCount];

    ts_qracc #(
        .numRows(numRows),
        .numCols(numCols),
        .numAdcBits(numAdcBits),
        .adcFullScale(adcFullScale)
    ) u_ts_qracc (
        .adc_ref_range_shifts(adc_ref_range_shifts),
        .binary_cfg(binary_cfg),
        .PSM_VDR_SEL(PSM_VDR_SEL),
        .PSM_VDR_SELB(PSM_VDR_SELB),
        .PSM_VSS_SEL(PSM_VSS_SEL),
        .PSM_VSS_SELB(PSM_VSS_SELB),
        .PSM_VRST_SEL(PSM_VRST_SEL),
        .PSM_VRST_SELB(PSM_VRST_SELB),
        .NSM_VDR_SEL(NSM_VDR_SEL),
        .NSM_VDR_SELB(NSM_VDR_SELB),
        .NSM_VSS_SEL(NSM_VSS_SEL),
        .NSM_VSS_SELB(NSM_VSS_SELB),
        .NSM_VRST_SEL(NSM_VRST_SEL),
        .NSM_VRST_SELB(NSM_VRST_SELB),
        .SA_OUT(SA_OUT),
        .WL(WL),
        .PCH(PCH),
        .WR_DATA(WR_DATA),
        .WRITE(WRITE),
        .CSEL(CSEL),
        .SAEN(SAEN),
        .ADC_OUT(ADC_OUT),
        .ADC_CODE(ADC_CODE),
        .NF(NF),
        .NFB(NFB),
        .M2A(M2A),
        .M2AB(M2AB),
        .R2A(R2A),
        .R2AB(R2AB),
        .CLK(clk)
    );

    always #(CLK_PERIOD/2) clk = ~clk;
    initial clk = 0;

    initial begin
        nrst = 0;
        adc_ref_range_shifts = 0;
        binary_cfg = 0;
        WL = '0;
        PCH = 0;
        WRITE = 0;
        WR_DATA = '0;
        CSEL = '0;
        SAEN = 0;
        PSM_VDR_SEL = '0; PSM_VDR_SELB = '1;
        PSM_VSS_SEL = '0; PSM_VSS_SELB = '1;
        PSM_VRST_SEL = '1; PSM_VRST_SELB = '0;
        NSM_VDR_SEL = '0; NSM_VDR_SELB = '1;
        NSM_VSS_SEL = '0; NSM_VSS_SELB = '1;
        NSM_VRST_SEL = '1; NSM_VRST_SELB = '0;
        NF = 0; NFB = 1; M2A = 0; M2AB = 1; R2A = 0; R2AB = 1;

        #(CLK_PERIOD * 2);
        nrst = 1;
        #(CLK_PERIOD * 2);

        // Fill every SRAM row with one (single-column memory).
        // Unit test: load the behavioural SRAM directly (the write protocol is
        // covered by the wr_controller tests).  Every row conducts.
        for (int r = 0; r < numRows; r++) begin
            u_ts_qracc.mem[r] = '1;
        end

        for (int mode = 0; mode < 2; mode++) begin
            binary_cfg = mode[0];
            for (int s = 0; s <= 8; s++) begin
                adc_ref_range_shifts = s[3:0];
                for (int m = -numRows; m <= numRows; m++) begin
                    int a, b;
                    a = (m > 0) ? m : 0;
                    b = (m < 0) ? -m : 0;
                    PSM_VDR_SEL = '0;
                    PSM_VSS_SEL = '0;
                    for (int i = 0; i < a; i++) PSM_VDR_SEL[i] = 1'b1;
                    for (int i = 0; i < b; i++) PSM_VSS_SEL[a + i] = 1'b1;
                    PSM_VRST_SEL = ~(PSM_VDR_SEL | PSM_VSS_SEL);
                    PSM_VDR_SELB = ~PSM_VDR_SEL;
                    PSM_VSS_SELB = ~PSM_VSS_SEL;
                    PSM_VRST_SELB = ~PSM_VRST_SEL;

                    #1;
                    decoded = $countones(therm_col) - adcMid;
                    $display("[ADC] n=%0d fs=%0d mode=%0d s=%0d mbl=%0d code=%0d therm=%0d dbg_mbl=%0d",
                             numAdcBits, adcFullScale, mode, s, m,
                             $signed(ADC_CODE[0]), decoded,
                             $signed(u_ts_qracc.mbl_value[0]));
                end
            end
        end

        $display("TEST SUCCESS");
        $finish();
    end

    initial begin
        #(CLK_PERIOD * 200000);
        $display("ERROR: WATCHDOG TIMED OUT");
        $finish();
    end

endmodule
