/* 
n-Bit input MAC accelerator
uses n cycles to complete an n-bit input mac
asdasd
*/

import qracc_pkg::*;

module qr_acc_top #(

    //  Parameters: Interface
    parameter dataInterfaceSize = 32,
    parameter ctrlInterfaceSize = 32,

    //  Parameters: CSRs
    parameter csrWidth = 32,
    parameter numCsr = 4,

    //  Parameters: QRAcc
    parameter qrAccInputBits = 4,
    parameter qrAccInputElements = 128,
    parameter qrAccOutputBits = 8,
    parameter qrAccOutputElements = 32,
    parameter qrAccAdcBits = 4,
    parameter qrAccAccumulatorBits = 16, // Internal parameter of seq acc

    //  Parameters: Global Buffer
    parameter globalBufferDepth = 1024,
    parameter globalBufferExtInterfaceWidth = 32,
    parameter globalBufferReadInterfaceWidth = 32,
    parameter globalBufferIntInterfaceWidth = qrAccInputElements*qrAccInputBits,
    parameter globalBufferAddrWidth = 32,
    parameter globalBufferDataSize = 8,          // Byte-Addressability

    // Parameters: Feature Loader
    parameter aflDimY = 128,
    parameter aflDimX = 6,
    parameter aflAddrWidth = 32
) (
    input clk, nrst,

    // Control Interface
    qracc_ctrl_interface periph_i,
    qracc_data_interface bus_i, 

    // Analog passthrough signals
    output to_analog_t to_analog,
    input from_analog_t from_analog,
    output from_sram_t from_sram,
    input to_sram_t to_sram
);


//-----------------------------------
// Signals
//-----------------------------------

// Signals : Control
qracc_config_t qracc_cfg;
qracc_control_t qracc_ctrl;

// Signals : Handshake
logic periph_handshake_success;
logic bus_handshake_success;

// Signals : QRAcc
logic [qrAccInputElements-1:0][qrAccInputBits-1:0] qracc_mac_data;
logic qracc_output_valid;
logic [qrAccOutputElements-1:0][qrAccAccumulatorBits-1:0] qracc_mac_output;
logic qracc_ready;

// Signals : Activation Buffer
logic [globalBufferReadInterfaceWidth-1:0] activation_buffer_rd_data;
logic [globalBufferIntInterfaceWidth-1:0] activation_buffer_int_wr_data;

// Signals: Output Scaler
logic [qrAccOutputElements-1:0][qrAccOutputBits-1:0] output_scaler_output;


//-----------------------------------
// Modules
//-----------------------------------

// Assigns
assign periph_handshake_success = periph_i.valid && periph_i.ready;
assign bus_handshake_success = bus_i.valid && bus_i.ready;

qracc_controller #(

) u_qracc_controller (
    .clk            (clk),
    .nrst           (nrst),

    .periph_i       (periph_i),
    .bus_i          (bus_i),
    .ctrl_o         (qracc_ctrl)
);

// Main matrix multiplication
seq_acc #(
    .inputBits        (qrAccInputBits),
    .inputElements    (qrAccInputElements),
    .outputElements   (qrAccOutputElements),
    .adcBits          (qrAccAdcBits),
    .accumulatorBits  (qrAccAccumulatorBits)
) u_seq_acc (
    .clk            (clk),
    .nrst           (nrst),
    
    .cfg            (qracc_cfg),
    
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
activation_buffer #(
    .dataSize           (globalBufferDataSize),
    .depth              (globalBufferDepth),
    .addrWidth          (globalBufferAddrWidth),
    .extInterfaceWidth  (globalBufferExtInterfaceWidth),
    .intInterfaceWidth  (globalBufferIntInterfaceWidth)
) u_activation_buffer (
    .clk                (clk),
    .nrst               (nrst),
    
    // External Interface
    .ext_wr_data_i          (bus_i.data_in),
    .ext_rd_data_o          (bus_i.data_out),
    .ctrl_ext_wr_en         (qracc_ctrl.activation_buffer_ext_wr_en),
    .ctrl_ext_rd_en         (qracc_ctrl.activation_buffer_ext_rd_en),

    // Internal Interface
    .int_wr_data_i          (activation_buffer_int_wr_data),
    .int_rd_data_o          (activation_buffer_rd_data),
    .ctrl_int_wr_en         (qracc_ctrl.activation_buffer_int_wr_en),
    .ctrl_int_rd_en         (qracc_ctrl.activation_buffer_int_rd_en),

    // For debug
    .write_head_snoop       ()
);

// Feature Loader - stages the input data for qrAcc
feature_loader #(
    .inputWidth        (aflAddrWidth),
    .addrWidth         (qrAccInputBits),
    .elementWidth      (qrAccInputElements),
    .numElements       (qrAccInputElements)
) u_feature_loader (
    .clk               (clk),
    .nrst              (nrst),

    // Interface with buffer
    .addr_i            (qracc_ctrl.feature_loader_addr),  
    .data_i            (activation_buffer_rd_data),
    .wr_en             (qracc_ctrl.feature_loader_wr_en),  
    
    // Interface with QR accelerator
    .data_o            (qracc_mac_data)
);

// Fixed point scaling from quantization methods in TFLite
output_scaler_set #(
    .numElements    (qrAccOutputElements),
    .inputWidth     (qrAccAccumulatorBits),
    .outputWidth    (qrAccOutputBits)
) u_output_scaler_set (
    .clk            (clk),
    .nrst           (nrst),
    
    .wx_i           (qracc_mac_output),
    .y_o            (output_scaler_output),

    .scale_w_en_i   (qracc_ctrl.output_scaler_scale_w_en),
    .scale_w_data_i (qracc_ctrl.output_scaler_scale_w_data),

    .shift_w_en_i   (qracc_ctrl.output_scaler_shift_w_en),
    .shift_w_data_i (qracc_ctrl.output_scaler_shift_w_data)
);

endmodule