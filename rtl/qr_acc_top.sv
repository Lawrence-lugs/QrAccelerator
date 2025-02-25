
/* 

n-Bit input MAC accelerator
uses n cycles to complete an n-bit input mac
asdasd
*/

import qracc_pkg::*;

module qr_acc_top #(
    parameter dataInterfaceSize = 32,
    parameter ctrlInterfaceSize = 16,
    parameter outBits = 8
) (
    input clk, nrst,

    // Control Interface
    input qracc_ctrl_intf 

    // Data Interface
    input [interfaceSize-1:0] data_i,
    input valid_i,
    output logic ready_o,

    // Passthrough signals
    output to_analog_t to_analog_o,
    input from_analog_t from_analog_i,
    
    output from_sram_t from_sram,
    input to_sram_t to_sram
);

// Parameters

// Signals
qracc_inst_t qracc_inst_q;
qracc_config_t qracc_cfg_q;

// Modules
// Instantiate both modules and connect their interfaces
seq_acc #(
    .inputBits(4),
    .inputElements(128),
    .outputBits(8),
    .outputElements(32),
    .adcBits(4)
) u_seq_acc (
    .clk(clk),
    .nrst(nrst),
    
    .cfg(cfg),
    
    .mac_data_i(mac_data),
    .mac_valid_i(mac_data_valid),
    .ready_o(ready_o),
    .valid_o(valid_o),
    .mac_data_o(mac_result),
    
    // Passthrough Signals
    .to_analog_o(to_analog),
    .from_analog_i(from_analog),
    .from_sram(from_sram),
    .to_sram(to_sram)
);

// Registers
always_ff @( posedge clk ) begin : qrAccTopRegs



end

// Datapaths

always_comb begin : qrAccTopDpath

end

endmodule