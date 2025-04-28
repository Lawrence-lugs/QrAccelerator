`timescale 1ns/1ps

`ifndef PYTEST_GENERATED_PARAMS
`define SRAM_ROWS 128
`define SRAM_COLS 32
`define QRACC_OUTPUT_BITS 16
`endif

`ifndef QRACC_PKG // evil hack for linting again
`define QRACC_PKG

package qracc_pkg;

    // QRAcc Parameters
    parameter numRows = `SRAM_ROWS;
    parameter numCols = `SRAM_COLS;
    parameter numAdcBits = 4; 
    parameter compCount = (2**numAdcBits)-1;
    parameter numCfgBits = 8;
    
    // Output Scaler Parameters
    parameter accumulatorBits = 16;
    parameter outputBits = `QRACC_OUTPUT_BITS;

    // Control signals for QRAcc
    typedef struct packed {
        // QRAcc
        logic qracc_mac_data_valid;

        // Activation buffer
        logic activation_buffer_ext_wr_en;
        logic activation_buffer_ext_rd_en;
        logic [31:0] activation_buffer_ext_wr_addr;
        logic [31:0] activation_buffer_ext_rd_addr;
        logic activation_buffer_int_wr_en;
        logic activation_buffer_int_rd_en;
        logic [31:0] activation_buffer_int_wr_addr;
        logic [31:0] activation_buffer_int_rd_addr;
        
        // Feature loader
        logic [31:0] feature_loader_addr;
        logic feature_loader_wr_en;

        logic output_scaler_scale_w_en;
        logic output_scaler_shift_w_en;
    } qracc_control_t;

    // Config that changes per-layer
    typedef struct packed {        
        logic [3:0] n_input_bits_cfg;  // config to generalize controller, partly still parametrized 
        logic [3:0] n_output_bits_cfg; // we don't use this yet (it's a parameter atm)

        logic binary_cfg; // binary or bipolar mode
        logic unsigned_acts; // unsigned or signed acts
        logic [2:0] adc_ref_range_shifts; // for analog IMC

        logic [3:0] filter_size_y;
        logic [3:0] filter_size_x;
        logic [31:0] input_fmap_size;  // H * W * C
        logic [31:0] output_fmap_size; // in number of elements
        logic [31:0] input_fmap_dimx;  // W
        logic [31:0] input_fmap_dimy;  // H
        logic [9:0] num_input_channels;
        logic [31:0] output_fmap_dimx; 
        logic [31:0] output_fmap_dimy;
        logic [9:0] num_output_channels;

        logic [9:0] mapped_matrix_offset_x;
        logic [9:0] mapped_matrix_offset_y;

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

    typedef struct {
        logic rq_ready_o; // if ready and valid; request is taken
        logic rd_valid_o; // once asserted; rdata is valid for read requests
        logic [numCols-1:0] rd_data_o;
    } from_sram_t;

    typedef struct {
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
);    

    logic [31:0] data;
    logic [31:0] read_data;
    logic [31:0] addr;
    logic wen;
    logic valid;
    logic ready;

    modport slave (
        input data, addr, wen, valid,
        output ready, read_data
    );

    modport master (
        output data, addr, wen, valid,
        input ready, read_data
    );

endinterface // qracc_ctrl_interface

interface qracc_data_interface #( // Generic data interface
);

    logic [31:0] data_in;
    logic [31:0] data_out;
    logic [31:0] addr;
    logic wen;
    logic valid;
    logic rd_data_valid;
    logic ready;

    modport slave (
        input data_in, addr, wen, valid,
        output ready, data_out, rd_data_valid
    );

    modport master (
        output data_in, addr, wen, valid,
        input ready, data_out, rd_data_valid
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

`endif
