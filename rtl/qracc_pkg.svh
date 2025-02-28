`timescale 1ns/1ps

package qracc_pkg;

    parameter numRows = 128;
    parameter numCols = 32;
    parameter numAdcBits = 4; 
    parameter compCount = (2**numAdcBits)-1;
    parameter numCfgBits = 8;

    typedef enum logic [3:0] {
        I_NOP,
        I_POINTER_RESET,
        I_LOAD_WEIGHT,
        I_LOAD_ACTIVATION,
        I_LOAD_OUTPUT,
        I_READ_ACTIVATION
    } global_buffer_instruction_t;

    typedef struct packed {        
        logic [numCfgBits-1:0] n_input_bits_cfg;
        logic binary_cfg; // binary or bipolar mode
        logic [2:0] adc_ref_range_shifts; // up to 8 shifts, depends on ADC, can be updated later for dynamic ADC ranging
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
    } to_column_analog_t;

    typedef struct {
        // SWITCH MATRIX
        logic [numRows-1:0] PSM_VDR_SEL;
        logic [numRows-1:0] PSM_VDR_SELB;
        logic [numRows-1:0] PSM_VSS_SEL;
        logic [numRows-1:0] PSM_VSS_SELB;
        logic [numRows-1:0] PSM_VRST_SEL;
        logic [numRows-1:0] PSM_VRST_SELB;

        logic [numRows-1:0] NSM_VDR_SEL;
        logic [numRows-1:0] NSM_VDR_SELB;
        logic [numRows-1:0] NSM_VSS_SEL;
        logic [numRows-1:0] NSM_VSS_SELB;
        logic [numRows-1:0] NSM_VRST_SEL;
        logic [numRows-1:0] NSM_VRST_SELB;

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

    typedef enum logic [3:0] { 
        I_READ_SRAM = 4'b0000,
        I_WRITE_SRAM = 4'b0001,
        I_MAC = 4'b0010,
        I_WRITE_CONFIG = 4'b0011
    } qracc_inst_t; // NEEDS OVERHAUL FOR MICROCODE LOOP



endpackage

interface qracc_ctrl_interface #( // Generic control interface
    parameter ctrlItfSize = 32
);    

    logic [31:0] data;
    logic addr;
    logic wen;
    logic valid;
    logic ready;

    modport slave (
        input data, addr, wen, valid,
        output ready
    );

    modport master (
        output data, addr, wen, valid,
        input ready
    );

endinterface // qracc_ctrl_interface

interface qracc_data_interface #( // Generic data interface
    parameter busSize = 32
);

    logic [31:0] data;
    logic addr;
    logic wen;
    logic valid;
    logic ready;

    modport slave (
        input data, addr, wen, valid,
        output ready
    );

    modport master (
        output data, addr, wen, valid,
        input ready
    );

endinterface // qracc_data_interface

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