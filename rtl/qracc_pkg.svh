

package qracc_pkg;

    typedef struct packed {
        // SWITCH MATRIX
        logic [numRows-1:0] VDR_SEL;
        logic [numRows-1:0] VDR_SELB;
        logic [numRows-1:0] VSS_SEL;
        logic [numRows-1:0] VSS_SELB;
        logic [numRows-1:0] VRST_SEL;
        logic [numRows-1:0] VRST_SELB;

        // SRAM
        logic [numRows-1:0] WL;
        logic PCH;
        logic [numCols-1:0] WR_DATA;
        logic WRITE;
        logic [numCols-1:0] CSEL;
        logic SAEN;

        // ADC
        logic NF;
        logic NFB;
        logic M2A;
        logic M2AB;
        logic R2A;
        logic R2AB;

        // Clock
        logic CLK;
    } analog_inputs_t;

    typedef struct packed {
        logic [numCols-1:0] SA_OUT,
        logic [compCount*numCols-1:0] ADC_OUT
    } analog_outputs_t;

endpackage