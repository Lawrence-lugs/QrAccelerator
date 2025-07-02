`timescale 1ns/1ps

`include "qracc_params.svh"

`ifndef QRACC_PKG // evil hack for linting again
`define QRACC_PKG
`endif


package qracc_pkg;

    // QRAcc Parameters
    parameter numRows = `SRAM_ROWS;
    parameter numCols    = 32;
    parameter numAdcBits = 4;
    parameter compCount  = (2**numAdcBits)-1;
    parameter numCfgBits = 8;
    parameter numBanks   = `SRAM_COLS/numCols;
    parameter outputElements = `SRAM_COLS;
    
      // Output Scaler Parameters
    parameter accumulatorBits = 16;
    parameter outputBits      = `QRACC_OUTPUT_BITS;
    parameter inputBits       = `QRACC_INPUT_BITS;

    // Trigger Values
    typedef enum logic [2:0] {
        TRIGGER_IDLE                = 0,
        TRIGGER_LOAD_ACTIVATION     = 1,
        TRIGGER_LOADWEIGHTS         = 2,
        TRIGGER_COMPUTE_ANALOG      = 3,
        TRIGGER_COMPUTE_DIGITAL     = 4,
        TRIGGER_READ_ACTIVATION     = 5,
        TRIGGER_LOADWEIGHTS_DIGITAL = 6,
        TRIGGER_LOAD_SCALER         = 7
    } qracc_trigger_t;

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

        // WSAcc
        logic wsacc_data_i_valid;
        logic wsacc_data_o_valid;
        logic wsacc_weight_itf_i_valid;
        logic wsacc_active;
        
        // Feature loader
        logic [31:0] feature_loader_addr;
        logic feature_loader_wr_en;

        logic output_scaler_scale_w_en;
        logic output_scaler_shift_w_en;
        logic output_scaler_offset_w_en;
        logic output_bias_w_en;

        logic [15:0] padding_start;
        logic [15:0] padding_end;
    } qracc_control_t;

    // Config that changes per-layer
    typedef struct packed {        

        // CSR 0: Main
        // 2:0 - csr_main_trigger
        // 3 - csr_main_clear
        // 4 - csr_main_busy = state_q == S_IDLE
        // 5 - csr_main_inst_write_mode = 1 if writing instructions
        // 7:5 - free
        // 11:8 - csr_main_internal_state = state_q of qracc_controller
        logic preserve_ifmap; // 12

        // CSR 1: Config
        logic binary_cfg;                       // 0 - binary or bipolar mode, binary if 1
        logic unsigned_acts;                    // 1 - unsigned or signed acts
        logic [3:0] adc_ref_range_shifts;       // 7:4
        logic [3:0] filter_size_y;              // 11:8
        logic [3:0] filter_size_x;              // 15:12
        logic [3:0] stride_x;                   // 19:16
        logic [3:0] stride_y;                   // 23:20
        logic [3:0] n_input_bits_cfg;           // 27:24 
        logic [3:0] n_output_bits_cfg;          // 31:28

        // CSR 2: Ifmap Dims
        logic [15:0] input_fmap_dimx;           // 15:0
        logic [15:0] input_fmap_dimy;           // 31:16

        // CSR 3: Ofmap Dims
        logic [15:0] output_fmap_dimx;          // 15:0
        logic [15:0] output_fmap_dimy;          // 31:16

        // CSR 4: Channels
        logic [15:0] num_input_channels;        // 15:0
        logic [15:0] num_output_channels;       // 31:16

        // CSR 5: Mapped Matrix Offsets
        logic [15:0] mapped_matrix_offset_x;    // 15:0
        logic [15:0] mapped_matrix_offset_y;    // 31:16

        // CSR 6: Padding Information
        logic [3:0] padding;                    // 3:0 - 1 if zeropad enabled
        logic [7:0] padding_value;              // 11:4
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
        logic [compCount*outputElements-1:0] ADC_OUT;
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

    // STATISTICS BROKERS

    typedef struct packed {
        int statActmemExtPortReads;
        int statActmemExtPortWrites;
        int statActmemIntPortReads;
        int statActmemIntPortWrites;

        int statFLReads;
        int statFLWrites;

        int statSeqAccWeightWrites;
        int statSeqAccOperations;
        int statSeqAccMacs;

        int statWQWrites;
        int statWQReads;
    } qracc_statistics_t;

    `ifdef TRACK_STATISTICS
    qracc_statistics_t stats;

    task reset_statistics();
        stats = 0;
    endtask
    
    // Task to write statistics to file
    task write_stats_to_file(string filename);
        int file_handle;
        file_handle = $fopen(filename, "w");
        if (file_handle) begin
            $fwrite(file_handle, "QRAcc Statistics Report\n");
            $fwrite(file_handle, "========================\n");
            $fwrite(file_handle, "Activation Memory Statistics:\n");
            $fwrite(file_handle, "  External Port Reads:  %0d\n", stats.statActmemExtPortReads);
            $fwrite(file_handle, "  External Port Writes: %0d\n", stats.statActmemExtPortWrites);
            $fwrite(file_handle, "  Internal Port Reads:  %0d\n", stats.statActmemIntPortReads);
            $fwrite(file_handle, "  Internal Port Writes: %0d\n", stats.statActmemIntPortWrites);
            $fwrite(file_handle, "\nFeature Loader Statistics:\n");
            $fwrite(file_handle, "  FL Reads:  %0d\n", stats.statFLReads);
            $fwrite(file_handle, "  FL Writes: %0d\n", stats.statFLWrites);
            $fwrite(file_handle, "\nSequential Accelerator Statistics:\n");
            $fwrite(file_handle, "  Weight Writes: %0d\n", stats.statSeqAccWeightWrites);
            $fwrite(file_handle, "  Operations:    %0d\n", stats.statSeqAccOperations);
            $fwrite(file_handle, "\nWeight Queue Statistics:\n");
            $fwrite(file_handle, "  WQ Writes: %0d\n", stats.statWQWrites);
            $fwrite(file_handle, "  WQ Reads:  %0d\n", stats.statWQReads);
            $fclose(file_handle);
            $display("Statistics written to file: %s", filename);
        end else begin
            $error("Could not open file %s for writing", filename);
        end
    endtask
    
    // Task to append statistics to CSV file for analysis
    task append_stats_to_csv(string filename, string event_name);
        int file_handle;
        static bit header_written = 0;
        
        if (!header_written) begin
            file_handle = $fopen(filename, "w");
            if (file_handle) begin
                $fwrite(file_handle, "EventName,Time,ActmemExtReads,ActmemExtWrites,ActmemIntReads,ActmemIntWrites,FLReads,FLWrites,SeqAccWeightWrites,SeqAccOperations,SeqAccMacs,WQWrites,WQReads\n");
                $fclose(file_handle);
                header_written = 1;
            end
        end
        
        file_handle = $fopen(filename, "a");
        if (file_handle) begin
            $fwrite(file_handle, "%s,%t,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d\n", 
                    event_name, 
                    $time,
                    stats.statActmemExtPortReads,
                    stats.statActmemExtPortWrites,
                    stats.statActmemIntPortReads,
                    stats.statActmemIntPortWrites,
                    stats.statFLReads, // There's actually no such thing
                    stats.statFLWrites,
                    stats.statSeqAccWeightWrites,
                    stats.statSeqAccOperations,
                    stats.statSeqAccMacs,
                    stats.statWQWrites,
                    stats.statWQReads);
            $fclose(file_handle);
        end else begin
            $error("Could not open file %s for appending", filename);
        end
    endtask
    `endif // TRACK STATISTICS

    // END STATISTICS BROKERS

    // Bus Interface Structs
    typedef struct packed {
        logic [31:0] data_in;
        logic [31:0] addr;
        logic wen;
        logic valid;
    } bus_req_t;

    typedef struct packed {
        logic ready;
        logic [31:0] data_out;
        logic rd_data_valid;
    } bus_resp_t;

endpackage
