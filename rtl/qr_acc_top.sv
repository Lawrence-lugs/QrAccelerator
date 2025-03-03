/* 
n-Bit input MAC accelerator
uses n cycles to complete an n-bit input mac
asdasd
*/

import qracc_pkg::*;

module qr_acc_top #(

    // Parameters: Interface
    parameter dataInterfaceSize = 32,
    parameter ctrlInterfaceSize = 32,

    //  Parameters: CSRs
    parameter csrWidth = 32,
    parameter numCsr = 4,

    //  Parameters: QRAcc
    parameter inputBits = 4,
    parameter inputElements = 128,
    parameter outputBits = 8,
    parameter outputElements = 32,

    //  Parameters: Global Buffer
    parameter globalBufferDepth = 1024,
    parameter globalBufferInterfaceWidth = 32,
    parameter globalBufferAddrWidth = 32,
    parameter globalBufferDataSize = 8          // Byte-Addressability
) (
    input clk, nrst,

    // Control Interface
    qracc_ctrl_interface periph_i, // Interface form for easy updates
    qracc_data_interface bus_i, 

    // Analog passthrough signals
    output to_analog_t to_analog,
    input from_analog_t from_analog,
    output from_sram_t from_sram,
    input to_sram_t to_sram
);

// Parameters

// Signals : Control
qracc_config_t qracc_cfg;
qracc_control_t qracc_ctrl;

// Signals : Handshake
logic periph_handshake_success;
logic bus_handshake_success;

// Signals : QRAcc
logic [inputElements-1:0][inputBits-1:0] qracc_mac_data;
logic qracc_output_valid;
logic [outputElements-1:0][outputBits-1:0] qracc_mac_output;
logic qracc_ready;

// Signals : Global Buffer
logic global_buffer_ready;

// Assigns
assign periph_handshake_success = periph_i.valid && periph_i.ready;
assign bus_handshake_success = bus_i.valid && bus_i.ready;

// Modules
// Instantiate both modules and connect their interfaces
seq_acc #(
    .inputBit       (inputBits),
    .inputElements  (inputElements),
    .outputBits     (outputBits),
    .outputElements (outputElements),
    .adcBits        (adcBits)
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

activation_buffer #(
    .dataSize       (globalBufferDataSize),
    .depth          (globalBufferDepth),
    .interfaceDepth (globalBufferInterfaceWidth),
    .addrWidth      (globalBufferAddrWidth)
) u_activation_buffer (
    .clk            (clk),
    .nrst           (nrst),
    
    // Write Interface
    .wr_data_i      (),
    .rd_data_o      (),
    .ctrl_wr_en     (),
    .ctrl_rd_en     ()
);



endmodule