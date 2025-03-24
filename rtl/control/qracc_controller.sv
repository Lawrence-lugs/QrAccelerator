// Overall controller for QRAcc
// Microcode looper

import qracc_pkg::*;

module qracc_controller #(
    parameter numCsr = 4
) (
    input clk, nrst,

    qracc_ctrl_interface periph_i,
    qracc_data_interface bus_i,

    // Signals to the people
    output qracc_control_t ctrl_o,
    output qracc_config_t cfg_o,

    // Signals from the people
    input stall_i,

    // Debugging
    output logic [31:0] debug_pc_o
);

///////////////////
// Parameters
///////////////////

parameter CSR_REGISTER_MAIN = 0;
parameter CSR_REGISTER_CONFIG = 1;
parameter CSR_REGISTER_STATUS = 2;

///////////////////
// Signals
///////////////////

logic [31:0] pc;
logic jump;
logic [31:0] jump_addr;

logic [31:0] csr [numCsr];
logic csr_main_clear;
logic csr_main_start;
logic csr_main_busy;
logic [31:0] csr_read_data;

logic periph_handshake;
logic periph_read;
logic periph_write;
assign periph_handshake = periph_i.valid && periph_i.ready;
assign periph_read      = periph_handshake && !periph_i.wen;
assign periph_write     = periph_handshake && periph_i.wen;

logic data_handshake;
logic data_read;
logic data_write;
assign data_handshake = bus_i.valid && bus_i.ready;
assign data_read      = data_handshake && !bus_i.wen;
assign data_write     = data_handshake && bus_i.wen;

///////////////////
// Modules
///////////////////

always_ff @( posedge clk or negedge nrst ) begin : pcControl
    if (!nrst) begin
        pc <= 0;
    end else begin
        if (!stall_i) begin
            pc <= pc + 1;
        end
    end    
end

// CSR
always_ff @( posedge clk or negedge nrst ) begin : csrControl
    if (!nrst) begin
        for (int i = 0; i < numCsr; i++) begin
            csr[i] <= 0;
        end
    end else begin
        if (periph_write) begin
            csr[periph_i.addr] <= periph_i.data;
        end
        if (periph_read) begin
            periph_i.read_data <= csr_read_data;
        end
    end
end
always_comb begin : csrReadDecode
    if (periph_read) begin
        case(periph_i.addr)
            CSR_REGISTER_MAIN: begin
                periph_i.read_data = {
                    29'b0,                  // 31:3 unused
                    1'b0,                   // CLEAR
                    csr_main_busy,          // BUSY
                    1'b0                    // START
                };
            end
            CSR_REGISTER_CONFIG: begin
                periph_i.read_data = csr[1];
            end
        endcase
    end else begin
        periph_i.read_data = 0;
    end
end
always_comb begin : csrDecode;
    csr_main_start =                csr[CSR_REGISTER_MAIN][0];
    csr_main_clear =                csr[CSR_REGISTER_MAIN][2];

    // Config 
    cfg_o.n_input_bits_cfg =        csr[CSR_REGISTER_CONFIG][2:0]; 
    cfg_o.binary_cfg       =        csr[CSR_REGISTER_CONFIG][3];
    cfg_o.adc_ref_range_shifts =    csr[CSR_REGISTER_CONFIG][6:4];
    
end



endmodule