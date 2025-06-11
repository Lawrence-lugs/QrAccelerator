/* 
n-Bit input DNN accelerator
uses n cycles to complete an n-bit input mac
asdasd
*/

`include "qracc_params.svh"

`timescale 1ns/1ps

import qracc_pkg::*;

module qr_acc_top #(

    //  Parameters: Interface
    parameter dataInterfaceSize = 32,
    parameter ctrlInterfaceSize = 32,

    //  Parameters: CSRs
    // parameter csrWidth = 32,
    // parameter numCsr = 4,

    //  Parameters: QRAcc
    parameter qrAccInputBits = `QRACC_INPUT_BITS,
    parameter qrAccInputElements = `SRAM_ROWS,
    parameter qrAccOutputBits = `QRACC_OUTPUT_BITS,
    parameter qrAccOutputElements = `SRAM_COLS,
    parameter qrAccAdcBits = 4,
    parameter qrAccAccumulatorBits = 16, // Internal parameter of seq acc

    //  Parameters: Per Bank
    parameter numRows = `SRAM_ROWS,
    parameter numCols = 32,
    parameter numBanks = `SRAM_COLS/numCols,

    //  Parameters: Global Buffer
    parameter globalBufferDepth = 2**8,
    parameter globalBufferExtInterfaceWidth = 32,
    parameter globalBufferIntInterfaceWidth = 256,
    parameter globalBufferAddrWidth = 32,
    parameter globalBufferDataSize = 8,          // Byte-Addressability

    // Parameters: Feature Loader
    parameter aflDimY = 128,
    parameter aflDimX = 6,
    parameter aflAddrWidth = 32,

    // Parameters: Addressing
    parameter csrBaseAddr = 32'h0000_0010, // Base address for CSR
    parameter accBaseAddr = 32'h0000_0100 // Base address for Accelerator
) (
    input clk, nrst,

    // Control Interface
    qracc_data_interface bus_i, 

    // Analog passthrough signals
    output to_analog_t to_analog,
    input from_analog_t from_analog,
    output [numBanks-1:0] bank_select

    // // CSR signals for testing for now
    // input qracc_config_t cfg,
    // input csr_main_clear,
    // output csr_main_busy,
    // input csr_main_inst_write_mode, // TODO: Remove?
    // input qracc_trigger_t csr_main_trigger,
    // output csr_main_internal_state
);


//-----------------------------------
// Signals
//-----------------------------------

// Signals : Control
qracc_config_t cfg;
qracc_control_t qracc_ctrl;
logic csr_main_clear;
logic csr_main_busy;
logic csr_main_inst_write_mode;
logic [3:0] csr_main_internal_state;
qracc_trigger_t csr_main_trigger;
logic [31:0] csr_rd_data;

// Signals : QRAcc
logic [qrAccInputElements-1:0][qrAccInputBits-1:0] qracc_mac_data;
logic qracc_output_valid;
logic [qrAccOutputElements-1:0][qrAccAccumulatorBits-1:0] qracc_mac_output;
logic qracc_ready;
to_sram_t to_sram;
from_sram_t from_sram; // no need to touch this for now, can use it later to read from sram

// Signals : Activation Buffer
logic [globalBufferIntInterfaceWidth-1:0] activation_buffer_rd_data;
logic [globalBufferIntInterfaceWidth-1:0] activation_buffer_int_wr_data;
logic [globalBufferAddrWidth-1:0] activation_buffer_int_wr_addr;
logic int_write_queue_valid_out;
logic [globalBufferExtInterfaceWidth-1:0] abuf_rd_data;

// Signals: Feature Loader and Padder
logic [globalBufferIntInterfaceWidth-1:0] activation_buffer_rd_data_padded; 

// Signals: Output Scaler
logic [qrAccOutputElements-1:0][qrAccOutputBits-1:0] output_scaler_output;
logic [qrAccOutputElements-1:0][qrAccOutputBits-1:0] aligned_output_scaler_output;

logic csr_rd_data_valid;

//-----------------------------------
// Modules
//-----------------------------------

qracc_csr #(
    .csrWidth                   (32),
    .numCsr                     (16),
    .CSR_BASE_ADDR              (csrBaseAddr) // Last hex is for CSR address
) u_csr (
    .clk                        (clk),
    .nrst                       (nrst),
    .bus_i                      (bus_i.slave),
    .cfg_o                      (cfg),
    .csr_rd_data_o              (csr_rd_data),
    .csr_rd_data_valid_o        (csr_rd_data_valid),
    .csr_main_clear             (csr_main_clear),
    .csr_main_trigger           (csr_main_trigger),
    .csr_main_busy              (csr_main_busy),
    .csr_main_inst_write_mode   (csr_main_inst_write_mode),
    .csr_main_internal_state    (csr_main_internal_state)
);

qracc_controller #(
    .numScalers                 (qrAccOutputElements),
    .numRows                    (qrAccInputElements),
    .internalInterfaceWidth     (globalBufferIntInterfaceWidth),
    .numBanks                   (numBanks)
) u_qracc_controller (
    .clk                        (clk),
    .nrst                       (nrst),

    .bus_i                      (bus_i.slave),

    .ctrl_o                     (qracc_ctrl),
    .to_sram                    (to_sram),
    .from_sram                  (from_sram),
    .bank_select                (bank_select),

    .qracc_output_valid         (qracc_output_valid),
    .qracc_ready                (qracc_ready),
    .int_write_queue_valid      (int_write_queue_valid_out),

    .cfg                        (cfg),
    .csr_main_clear             (csr_main_clear),
    .csr_main_trigger           (csr_main_trigger),
    .csr_main_busy              (csr_main_busy),
    .csr_main_inst_write_mode   (csr_main_inst_write_mode),
    .csr_main_internal_state    (csr_main_internal_state),
    .csr_rd_data_valid          (csr_rd_data_valid),

    .debug_pc_o                 () 
);

// Main matrix multiplication
seq_acc #(
    .maxInputBits     (qrAccInputBits),
    .inputElements    (qrAccInputElements),
    .outputElements   (qrAccOutputElements),
    .numCols          (numCols), // per bank
    .adcBits          (qrAccAdcBits),
    .accumulatorBits  (qrAccAccumulatorBits)
) u_seq_acc (
    .clk            (clk),
    .nrst           (nrst),
    
    .cfg            (cfg),
    
    .mac_data_i     (qracc_mac_data),
    .mac_valid_i    (qracc_ctrl.qracc_mac_data_valid),
    .ready_o        (qracc_ready),
    .valid_o        (qracc_output_valid),
    .mac_data_o     (qracc_mac_output),
    
    // Passthrough Signals
    .to_analog_o    (to_analog),
    .from_analog_i  (from_analog),
    .from_sram      (from_sram),
    .to_sram        (to_sram)
);

// Main feature map buffer
localparam oscalerOutputSize = qrAccOutputBits*qrAccOutputElements;
localparam oscalerExtendBits = globalBufferIntInterfaceWidth - oscalerOutputSize;
ram_2w2r #(
    .dataSize           (globalBufferDataSize),
    .depth              (globalBufferDepth),
    .addrWidth          (globalBufferAddrWidth),
    .interfaceWidth1    (globalBufferExtInterfaceWidth),
    .interfaceWidth2    (globalBufferIntInterfaceWidth)
) u_activation_buffer (
    .clk                (clk),
    .nrst               (nrst),
    
    // External Interface
    .wr_data_1_i        (bus_i.data_in),
    .wr_en_1_i          (qracc_ctrl.activation_buffer_ext_wr_en),
    .wr_addr_1_i        (qracc_ctrl.activation_buffer_ext_wr_addr),
    .rd_data_1_o        (abuf_rd_data),
    .rd_addr_1_i        (qracc_ctrl.activation_buffer_ext_rd_addr),
    .rd_en_1_i          (qracc_ctrl.activation_buffer_ext_rd_en),

    // Internal Interface
    .wr_data_2_i       (activation_buffer_int_wr_data),
    .wr_en_2_i         (int_write_queue_valid_out),
    .wr_addr_2_i       (activation_buffer_int_wr_addr),
    .rd_data_2_o       (activation_buffer_rd_data),
    .rd_addr_2_i       (qracc_ctrl.activation_buffer_int_rd_addr),
    .rd_en_2_i         (qracc_ctrl.activation_buffer_int_rd_en)
);

// Padder - implements hardware padding
padder #(
    .elementWidth    (qrAccInputBits),
    .numElements     (globalBufferIntInterfaceWidth / qrAccInputBits)
) u_padder (
    .data_i          (activation_buffer_rd_data),           
    .pad_start       (qracc_ctrl.padding_start),        
    .pad_end         (qracc_ctrl.padding_end),          
    .pad_value       (cfg.padding_value),        
    .data_o          (activation_buffer_rd_data_padded)           
);

// Feature Loader - stages the input data for qrAcc
feature_loader #(
    .inputWidth        (globalBufferIntInterfaceWidth),
    .addrWidth         (aflAddrWidth),
    .elementWidth      (qrAccInputBits),
    .numElements       (qrAccInputElements)
) u_feature_loader (
    .clk               (clk),
    .nrst              (nrst),

    // Interface with buffer
    .addr_i            (qracc_ctrl.feature_loader_addr),  
    .data_i            (activation_buffer_rd_data_padded), // Padded data from activation buffer
    .wr_en             (qracc_ctrl.feature_loader_wr_en),  
    
    // Interface with QR accelerator
    .data_o            (qracc_mac_data),

    .mask_start        (cfg.mapped_matrix_offset_y),
    .mask_end          (cfg.filter_size_y * cfg.filter_size_x * cfg.num_input_channels + cfg.mapped_matrix_offset_y)
);

// Fixed point scaling from quantization methods in TFLite
output_scaler_set #(
    .numElements    (qrAccOutputElements),
    .inputWidth     (qrAccAccumulatorBits),
    .outputWidth    (qrAccOutputBits),
    .scaleBits      (16),
    .shiftBits      (4)
) u_output_scaler_set (
    .clk            (clk),
    .nrst           (nrst),
    
    .wx_i           (qracc_mac_output),
    .y_o            (output_scaler_output),

    .scale_w_en_i   (qracc_ctrl.output_scaler_scale_w_en),
    .scale_w_data_i (bus_i.data_in[4+:16]),

    .shift_w_en_i   (qracc_ctrl.output_scaler_shift_w_en),
    .shift_w_data_i (bus_i.data_in[3:0]),
    
    .offset_w_en_i   (qracc_ctrl.output_scaler_offset_w_en),
    .offset_w_data_i (bus_i.data_in[20+:8]),

    .bias_w_en_i    (qracc_ctrl.output_bias_w_en),
    .bias_w_data_i  (bus_i.data_in[31:0]),

    .cfg_unsigned   (cfg.unsigned_acts),
    .cfg_output_bits(cfg.n_output_bits_cfg)
);

mm_output_aligner #(
    .numColsPerBank (numCols),
    .elementBits    (qrAccOutputBits),
    .numElements    (qrAccOutputElements)
) u_mm_output_aligner (
    .data_i         (output_scaler_output),
    .cfg_i          (cfg),
    .data_o         (aligned_output_scaler_output)
);

logic [numBanks-1:0] piso_write_queue_valid_in;
logic [numBanks-1:0][globalBufferAddrWidth-1:0] piso_write_queue_addr_in;
always_comb begin
    piso_write_queue_valid_in = '0;
    piso_write_queue_addr_in = '0;
    for (int i = 0; i < numBanks; i++) begin
        piso_write_queue_valid_in[i] = qracc_ctrl.activation_buffer_int_wr_en && ( 
            ( cfg.num_output_channels > (numCols * i)) );
        piso_write_queue_addr_in[i] = qracc_ctrl.activation_buffer_int_wr_addr + (i * numCols);
    end
end

piso_write_queue #(
    .numParallelIn       (numBanks),
    .writeInterfaceWidth (globalBufferIntInterfaceWidth),
    .queueDepth          ( (qrAccOutputElements/numCols)*2 ), 
    .maxBits             (8),
    .writeAddrWidth      (globalBufferAddrWidth)
) u_piso_write_queue (
    .clk            (clk),
    .nrst           (nrst),

    .data_in        (aligned_output_scaler_output), // must always be equal to numBanks * oscalerOutputSize
    .addr_in        (piso_write_queue_addr_in),
    .valid_in       (piso_write_queue_valid_in),
    .ready_out      (), // Not connected since writing to internal interface

    .addr_out       (activation_buffer_int_wr_addr), // Writing to internal interface
    .data_out       (activation_buffer_int_wr_data), // Writing to internal interface
    .valid_out      (int_write_queue_valid_out) // Valid signal for internal interface
);

// Manage bus output
always_comb begin : busOutputManage
    
    case(bus_i.addr & 32'hFFFF_FFF0) // Mask for base address
        csrBaseAddr: begin
            // CSR Read Data
            bus_i.data_out = csr_rd_data;
        end
        accBaseAddr: begin
            // QRAcc Output Data
            bus_i.data_out = abuf_rd_data;
        end
        default: begin
            bus_i.data_out = '0; // Default case, return zero
        end
    endcase
end

endmodule