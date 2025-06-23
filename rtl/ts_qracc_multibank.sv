/* 

Multibank version of qracc test schematic
Does not yet have an actual schematic

To implement, this must be PnRed and integrated together the QRAcc analog 

*/
`timescale 1ns/1ps

module ts_qracc_multibank #(
    parameter numRows = 128,
    parameter numCols = 8,
    parameter numAdcBits = 4,
    localparam compCount = (2**numAdcBits)-1, // An ADC only has 2^numAdcBits-1 comparators
    parameter numBanks = 8
) (

    input logic [3:0] adc_ref_range_shifts,
    input logic [numBanks-1:0] bank_select,

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
    output logic [compCount*numCols*numBanks-1:0] ADC_OUT, // the only non-banked signal
    input logic NF,
    input logic NFB,
    input logic M2A,
    input logic M2AB,
    input logic R2A,
    input logic R2AB,

    // Clock
    input logic CLK
);
// Intermediate wires for each bank
logic [numBanks-1:0][numCols-1:0] sa_out_bank;
logic [numBanks-1:0] pch_bank;
logic [numBanks-1:0] write_bank;
logic [numBanks-1:0][numCols-1:0] csel_bank;
logic [numBanks-1:0] saen_bank;

// Always_comb block to handle bank selection
always_comb begin
    for (int i = 0; i < numBanks; i++) begin
        SA_OUT = bank_select[i] ? sa_out_bank[i] : '0;
        pch_bank[i] = bank_select[i] ? PCH : '0;
        write_bank[i] = bank_select[i] ? WRITE : '0;
        csel_bank[i] = bank_select[i] ? CSEL : '0;
        saen_bank[i] = bank_select[i] ? SAEN : '0;
    end
end

// Generate ts_qracc instances
generate
    for(genvar i=0; i<numBanks; i++) begin : qracc_bank
        ts_qracc #(
            .numRows(numRows),
            .numCols(numCols),
            .numAdcBits(numAdcBits)
        ) qracc (
            .adc_ref_range_shifts(adc_ref_range_shifts),

            // ANALOG INTERFACE : SWITCH MATRIX
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

            // ANALOG INTERFACE : SRAM
            .SA_OUT(sa_out_bank[i]),
            .WL(WL),
            .PCH(pch_bank[i]),
            .WR_DATA(WR_DATA),
            .WRITE(write_bank[i]),
            .CSEL(csel_bank[i]),
            .SAEN(saen_bank[i]),

            // ANALOG INTERFACE : ADC
            .ADC_OUT(ADC_OUT[(i+1)*compCount*numCols-1:i*compCount*numCols]),
            .NF(NF),
            .NFB(NFB),
            .M2A(M2A),
            .M2AB(M2AB),
            .R2A(R2A),
            .R2AB(R2AB),

            // Clock
            .CLK(CLK)
        );
    end
endgenerate


endmodule