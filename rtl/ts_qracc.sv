/*
 * Models the ts_column for the digital parts.
 *
 * TIMING / ANALOG CO-SIMULATION NOTE (2026-11-18)
 * ------------------------------------------------
 * This model is purely combinational from its switch-matrix select / WL ports
 * to ADC_OUT.  The digital wrapper used to blank every PSM/NSM select on
 * `clk && mac_en_i`, i.e. it only drove data during the low phase.  That was
 * removed (FINDINGS §11.1): selects are now data-valid for the whole MAC word
 * and are blanked only between words.  Any analog testbench or VAMS schematic
 * that sampled the column on a particular clock phase MUST be re-timed and
 * re-verified against this model -- the ADC aperture / sample instant assumed
 * by the analog side is no longer the same as the digital side.  CLK is still
 * used for the behavioural SRAM write model.
 *
 * ADC_CODE is a digital test tap for wide behavioural converters.  It is not
 * part of the analog interface; the physical interface remains the
 * thermometer bus ADC_OUT.
 */
import qracc_pkg::*;

module ts_qracc #(

    // These are defined as localparams for ease of change
    // But so that we also don't need to set values when synthesizing
    parameter numRows = 128,
    parameter numCols = 8,
    parameter numAdcBits = 4,
    // Half-span in column-current counts at adc_ref_range_shifts == 0.
    // MUST be a power of two: the ADC model is implemented with shifts only.
    parameter int adcFullScale = (1 << numAdcBits),
    parameter int numPlanes = 8,
    localparam compCount = (2**numAdcBits)-1 // An ADC only has 2^numAdcBits-1 comparators
) (
    // DIGITAL SETTING
    input [3:0] adc_ref_range_shifts,
    // 0 - bipolar ladder ([-VDD,+VDD]), 1 - binary ladder ([0,VDD]).
    // Selects which half of the ladder the clamp allows; see the ADC model
    // comment below.
    input logic binary_cfg,

    // ANALOG INTERFACE : SWITCH MATRIX
    input logic [numRows-1:0] PSM_VDR_SEL,
    input logic [numRows-1:0] PSM_VDR_SELB,
    input logic [numRows-1:0] PSM_VSS_SEL,
    input logic [numRows-1:0] PSM_VSS_SELB,
    input logic [numRows-1:0] PSM_VRST_SEL,
    input logic [numRows-1:0] PSM_VRST_SELB,

    input logic [numRows-1:0] NSM_VDR_SEL,
    input logic [numRows-1:0] NSM_VDR_SELB,
    input logic [numRows-1:0] NSM_VSS_SEL,
    input logic [numRows-1:0] NSM_VSS_SELB,
    input logic [numRows-1:0] NSM_VRST_SEL,
    input logic [numRows-1:0] NSM_VRST_SELB,

    // ANALOG INTERFACE : SRAM
    output logic [numCols-1:0] SA_OUT,
    input logic [numRows-1:0] WL,
    input logic PCH,
    input logic [numCols-1:0] WR_DATA,
    input logic WRITE,
    input logic [numCols-1:0] CSEL,
    input logic SAEN,

    // ANALOG INTERFACE : ADC
    output logic [compCount*numCols-1:0] ADC_OUT,
    // Digital code tap (same value the thermometer encodes), sign-extended.
    output logic signed [numCols-1:0][qrAccAdcCodeBits-1:0] ADC_CODE,
    input logic NF,
    input logic NFB,
    input logic M2A,
    input logic M2AB,
    input logic R2A,
    input logic R2AB,

    // Clock
    input logic CLK
);

// SRAM modelling
logic [numCols-1:0] mem [numRows];
`ifdef DEBUG
integer dbg_sram_wr = 0;
integer dbg_mbl_shown = 0;
`endif
always_ff @( posedge CLK ) begin :  sramModel
    if (PCH) begin
        if (WRITE) begin
            for (int i = 0; i < numRows; i++) begin
                if (WL[i]) begin 
                    mem[i] = WR_DATA; // blocking assignment in behavioral SRAM model
`ifdef DEBUG
                    dbg_sram_wr = dbg_sram_wr + 1;
                    if (dbg_sram_wr <= 20 || (i >= 192 && i <= 218))
                        $display("[DBG sram-wr] %m n=%0d row=%0d word=%h", dbg_sram_wr, i, WR_DATA);
`endif
                    // $display("WR_DATA: %d, %d", WR_DATA, mem[i]);
                end
            end
        end
    end
end
// SA output is not registered
always_comb begin : readModel
    if (PCH && SAEN) begin
        for (int i = 0; i < numRows; i++) begin
            if (WL[i]) SA_OUT = mem[i];
        end
    end else begin
        SA_OUT = 0;
    end
end


// MAC modelling
logic signed [31:0] mbl_value [numCols];
logic signed [numAdcBits-1:0] adc_code [numCols];
logic signed [numCols-1:0][compCount-1:0] comp_out;

// ---------------------------------------------------------------------------
// ADC reference model (fixed full scale, `s` zooms toward V_RST)
//
// Hardware behaviour (specified 2026-11-18):
//   * The flash ADC has a FIXED full-scale range.  In bipolar mode it spans
//     [-VDD, +VDD] with V_RST = 0; in binary mode it spans [0, VDD] with
//     V_RST = VDD/2.  Either way V_RST is the zero of the column current
//     (mbl_value == 0 with every switch at VRST).
//   * numAdcBits comparators subdivide that fixed span into 2**numAdcBits
//     levels, so extra comparators buy RESOLUTION, never extra range.
//   * adc_ref_range_shifts (s) scales the reference span TOWARDS V_RST: each
//     increment halves the span, so the LSB becomes 2**s finer and the
//     conversion saturates 2**s earlier.
//
// In count units, with adcFullScale = counts for the half-span at s = 0:
//
//     lsb  = adcFullScale / 2**(numAdcBits - 1 + s)
//     code = clamp(round_half_up(mbl / lsb), code_min, code_max)
//
// This is bit-identical to qracc_marp.quantization.quant.adc_quantize.
// adcFullScale MUST be a power of two so the division is a shift.
//
// Consequence for binary mode: the plane partial is unipolar (0..numRows
// counts) while the ladder is centred on V_RST, so only the upper half of the
// codes (0 .. 2**(numAdcBits-1)-1) can ever be used.
// ---------------------------------------------------------------------------
localparam int adcCodeMax = (1 <<< (numAdcBits-1)) - 1;
localparam int adcCodeMinBipolar = -(1 <<< (numAdcBits-1));
localparam int adcForwardShift = numAdcBits - 1; // lsb exponent at s = 0
localparam int adcMid = 1 <<< (numAdcBits-1);

always_comb begin : toMBL
    int lsb_exp;
    int code_min;
    int code_i;
    logic signed [63:0] numer;
`ifdef ADC_MODEL_LEGACY
    int legacy_max;
    int legacy_min;
    int legacy_round;
`endif

    code_min = binary_cfg ? 0 : adcCodeMinBipolar;
    // lsb = 2**lsb_exp, lsb_exp = log2(adcFullScale) - (numAdcBits-1+s)
    lsb_exp = $clog2(adcFullScale) - adcForwardShift
              - int'(adc_ref_range_shifts);

    for (int j = 0; j < numCols; j++) begin
        mbl_value[j] = 0;
        for (int i = 0; i < numRows; i++) begin
            if(mem[i][j] == 1) begin
                mbl_value[j] += PSM_VDR_SEL[i];
                mbl_value[j] -= PSM_VSS_SEL[i];
            end else begin
                mbl_value[j] += NSM_VDR_SEL[i];
                mbl_value[j] -= NSM_VSS_SEL[i];
            end
        end

`ifdef ADC_MODEL_LEGACY
        // Historical model: s widens the window by 2**s and coarsens the
        // LSB by 2**s (a digital attenuation).  Compile-time only: it is
        // stripped from every normal build so it cannot reach synthesis.
        begin
            legacy_max = (1 << (numAdcBits + adc_ref_range_shifts - 1)) - 1;
            legacy_min = -(1 << (numAdcBits + adc_ref_range_shifts - 1));
            if (adc_ref_range_shifts == 0)
                legacy_round = 0;
            else
                legacy_round = (mbl_value[j] >> (adc_ref_range_shifts - 1)) & 1;

            if (mbl_value[j] > legacy_max)
                code_i = adcCodeMax;
            else if (mbl_value[j] < legacy_min)
                code_i = adcCodeMinBipolar;
            else
                code_i = int'($signed(
                    mbl_value[j][adc_ref_range_shifts +: numAdcBits]))
                    + ((adc_ref_range_shifts > 1) ? legacy_round : 0);
        end
`else
            // round-half-up(mbl / lsb), with lsb an exact power of two.
            if (lsb_exp > 0) begin
                numer = $signed(mbl_value[j]) + (64'sd1 <<< (lsb_exp-1));
                code_i = int'(numer >>> lsb_exp);
            end else if (lsb_exp == 0) begin
                code_i = int'($signed(mbl_value[j]));
            end else begin
                // LSB finer than one count: the code is an exact left shift.
                numer = $signed(mbl_value[j]) <<< (-lsb_exp);
                code_i = int'(numer);
            end

            if (code_i > adcCodeMax) code_i = adcCodeMax;
            if (code_i < code_min)   code_i = code_min;
`endif
        adc_code[j] = code_i;

        // Dump raw mbl and the ADC decision (+define+DEBUG)
        `ifdef DEBUG
        if (dbg_mbl_shown == 0 && mbl_value[j] != 0) begin
            $display("[DBG ts_qracc] s=%0d binary=%0d fs=%0d lsb_exp=%0d mbl=%0d code=%0d",
                     adc_ref_range_shifts, binary_cfg, adcFullScale, lsb_exp,
                     mbl_value[j], $signed(adc_code[j]));
            dbg_mbl_shown = 1;
        end
        `endif
    end

    // Decode the ADC code into the thermometer comparator bus.  A code c
    // lights comparators 0 .. (c + 2**(N-1) - 1), i.e. the count above V_RST.
    for (int j = 0; j < numCols; j++) begin
        for (int i = 0; i < compCount; i++) begin
            comp_out[j][i] = ((int'($signed(adc_code[j])) + adcMid) > i) ? 1'b1 : 1'b0;
        end
    end

    ADC_OUT = comp_out;
    for (int j = 0; j < numCols; j++) begin
        ADC_CODE[j] = adc_code[j];
    end
end

`ifdef DEBUG
final begin
    for (int r = 0; r < numRows; r++) begin
        if (mem[r] != '0)
            $display("[DBG sram] %m r=%0d word=%h", r, mem[r]);
    end
end
`endif

endmodule