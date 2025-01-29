`timescale 1ns/1ps

package qracc_pkg;

    parameter numRows = 128;
    parameter numCols = 32;
    parameter numAdcBits = 4; 
    parameter compCount = (2**numAdcBits)-1;
    parameter numCfgBits = 8;

    typedef struct packed {        
        logic [numCfgBits-1:0] n_input_bits_cfg;
        // logic [numCfgBits-1:0] n_adc_bits_cfg;
        logic binary_cfg;
        logic [2:0] adc_ref_range_shifts; // up to 8 shifts
    } qracc_config_t;

    typedef struct {
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
    } to_analog_t;

    typedef struct {
        logic [numCols-1:0] SA_OUT;
        logic [compCount*numCols-1:0] ADC_OUT;
    } from_analog_t;

    typedef struct packed {
        logic rq_ready_o; // if ready and valid; request is taken
        logic rd_valid_o; // once asserted; rdata is valid for read requests
        logic [numCols-1:0] rd_data_o;
    } from_sram_t;

    typedef struct packed {
        logic rq_wr_i; // write or read request
        logic rq_valid_i; // request is valid
        logic [numCols-1:0] wr_data_i;
        logic [$clog2(numRows)-1:0] addr_i;
    } to_sram_t;

endpackage


interface sram_itf #(
    parameter numRows = 128,
    parameter numCols = 32
);
    // DIGITAL INTERFACE: SRAM
    logic rq_wr_i; // write or read request
    logic rq_valid_i; // request is valid
    logic rq_ready_o; // if ready and valid; request is taken
    logic rd_valid_o; // once asserted; rdata is valid for read requests
    logic [numCols-1:0] rd_data_o;
    logic [numCols-1:0] wr_data_i;
    logic [$clog2(numRows)-1:0] addr_i;

    modport slave (
        input rq_wr_i, // write or read request
        input rq_valid_i, // request is valid
        output rq_ready_o, // if ready and valid; request is taken
        output rd_valid_o, // once asserted; rdata is valid for read requests
        output rd_data_o,
        input wr_data_i,
        input addr_i
    );

    modport master (
        output rq_wr_i, // write or read request
        output rq_valid_i, // request is valid
        input rq_ready_o, // if ready and valid; request is taken
        input rd_valid_o, // once asserted; rdata is valid for read requests
        input rd_data_o,
        output wr_data_i,
        output addr_i
    );

endinterface //sram_itf