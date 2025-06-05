// CSR Implementation inspired by sir Ry

import qracc_pkg::*;
module csr #(
    parameter csrWidth = 32,
    parameter numCsr = 16,
    parameter CSR_BASE_ADDR = 32'h0000_0010 // Last hex is for CSR address
) (
    input clk, nrst,

    qracc_data_interface bus_i,

    // CSR signals
    output qracc_config_t cfg_o,
    output csr_main_clear,
    output qracc_trigger_t csr_main_trigger,
    input csr_main_busy,
    output csr_main_inst_write_mode,
    input [3:0] csr_main_internal_state
);

// Parameters
localparam CSR_BASE_MASK = 32'hFFFF_FFF0; // Mask for base address
typedef enum logic [3:0] { 
    CSR_REG_MAIN = 0,
    CSR_REG_CONFIG = 1,
    CSR_REG_IFMAP_DIMS = 2,
    CSR_REG_OFMAP_DIMS = 3,
    CSR_REG_CHANNELS = 4
} csr_names_t;

// Signals
logic [csrWidth-1:0] csr_set [numCsr];
logic handshake_success;
logic [3:0] csr_addr;
logic kausap_ako;
logic [31:0] csr_main_read_output;

// Assignments
// Kausap ba ako
always_comb begin : csrAddressed
    kausap_ako = (bus_i.addr & CSR_BASE_MASK) == CSR_BASE_ADDR;
    handshake_success = bus_i.valid && bus_i.ready && kausap_ako;
end

// CSR Decode
always_comb begin : csrDecode
    csr_main_read_output = {
        3'b0, // csr_main_trigger
        1'b0, // csr_main_clear
        csr_main_busy, // csr_main_busy
        3'b0, // free
        csr_main_internal_state,
        20'b0 // free
    };

    if (handshake_success && (csr_addr == CSR_REG_MAIN)) begin
        csr_main_trigger = qracc_trigger_t'(bus_i.data_in[2:0]);
        csr_main_clear = bus_i.data_in[3]; 
        csr_main_inst_write_mode = bus_i.data_in[5];
    end else begin
        csr_main_trigger = TRIGGER_IDLE;
        csr_main_clear = 1'b0;
        csr_main_inst_write_mode = 1'b0;
    end
end

// CSR Write & Reads
always_ff @( posedge clk or negedge nrst ) begin : csrWriteReads
    if (!nrst) begin
        for(int i = 0; i < numCsr; i++) begin
            csr_set[i] <= 0;
        end
    end else begin
        if (handshake_success) begin
            // Write to CSR
            if (bus_i.wen) begin
                csr_set[csr_addr] <= bus_i.data_in;
            end else begin
                // Read from CSR
                case (csr_addr)
                    CSR_REG_MAIN: begin
                        bus_i.data_out <= csr_main_read_output;
                    end
                    CSR_REG_CONFIG: begin
                        bus_i.data_out <= csr_set[CSR_REG_CONFIG];
                    end
                    CSR_REG_IFMAP_DIMS: begin
                        bus_i.data_out <= csr_set[CSR_REG_IFMAP_DIMS];
                    end
                    CSR_REG_OFMAP_DIMS: begin
                        bus_i.data_out <= csr_set[CSR_REG_OFMAP_DIMS];
                    end
                    CSR_REG_CHANNELS: begin
                        bus_i.data_out <= csr_set[CSR_REG_CHANNELS];
                    end
                    default: begin
                        bus_i.data_out <= 32'h0000_0000; // Default case, return zero
                    end
                endcase
            end
        end
    end
end

endmodule