`timescale 1ns/1ps

import qracc_pkg::*;

module csr #(
    parameter numCsr = 4,
    parameter csrWidth = 32
) (
    input clk, nrst,

    input [csrWidth-1:0] csr_data_i,
    input csr_wr_en_i,
    input csr_rd_en_i,
    input [$clog2(numCsr)-1:0] csr_addr_i,
    output logic [csrWidth-1:0] csr_data_o,

    output qracc_config_t cfg_o,
    output logic csr_main_clear,
    output logic csr_main_start,
    input  csr_main_busy,
    output logic csr_main_inst_write_mode
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

logic [31:0] csr [numCsr];

///////////////////
// Logic
///////////////////

// CSR
always_ff @( posedge clk or negedge nrst ) begin : csrControl
    if (!nrst) begin
        for (int i = 0; i < numCsr; i++) begin
            csr[i] <= 0;
        end
    end else begin
        if (csr_wr_en_i) begin
            csr[csr_addr_i] <= csr_data_i;
        end
    end
end
always_comb begin : csrReadDecode
    if (csr_rd_en_i) begin
        case(csr_addr_i)
            CSR_REGISTER_MAIN: begin
                csr_data_o = {
                    28'b0,                  // 31:4 unused
                    1'b0,                   // INSTRUCTION WRITE MODE
                    1'b0,                   // CLEAR
                    csr_main_busy,          // BUSY
                    1'b0                    // START
                };
            end
            CSR_REGISTER_CONFIG: begin
                csr_data_o = csr[1];
            end
        endcase
    end else begin
        csr_data_o = 0;
    end
end
always_comb begin : csrDecode

    // CSR Main
    if (csr_wr_en_i && csr_addr_i == CSR_REGISTER_MAIN) begin
        csr_main_start = csr_data_i[0];
        csr_main_clear = csr_data_i[1];
    end else begin
        csr_main_start = 0;
        csr_main_clear = 0;
    end
    csr_main_inst_write_mode = csr[CSR_REGISTER_MAIN][3];

    // Config 
    cfg_o.n_input_bits_cfg =        csr[CSR_REGISTER_CONFIG][2:0]; 
    cfg_o.binary_cfg       =        csr[CSR_REGISTER_CONFIG][3];
    cfg_o.adc_ref_range_shifts =    csr[CSR_REGISTER_CONFIG][6:4];

end

    
endmodule