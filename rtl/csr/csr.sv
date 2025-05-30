// CSR Implementation inspired by sir Ry

import qracc_pkg::*;

module csr #(
    parameter csrWidth = 32
) (
    input clk, nrst,

    qracc_ctrl_interface periph_i,

    // CSR signals
    output qracc_config_t cfg_o,
    output csr_main_clear,
    output qracc_trigger_t csr_main_trigger,
    input csr_main_busy,
    output csr_main_inst_write_mode,
);

// Parameters
localparam CSR_REG_CORE = 0;
localparam CSR_REG_STATUS = 1;
localparam CSR_REG_CONFIG = 2;

// Signals
logic [csrWidth-1:0] csr_set [numCsr];
logic handshake_success;

// Assignments
assign handshake_success = periph_i.valid && periph_i.ready;

// CSR Write & Reads
always_ff @( posedge clk or negedge nrst ) begin : csrWriteReads
    if (!nrst) begin
        for(int i = 0; i < numCsr; i++) begin
            csr_set[i] <= 0;
        end
    end else begin
        if(periph_i.wen) begin
            if(handshake_success) begin
                csr_set[periph_i.addr] <= periph_i.data;
            end
        end else begin
            // Reads decode
            if(handshake_success) begin
                case(periph_i.addr)
                    CSR_REG_STATUS: periph_i.data <= {
                        {csrWidth-1{1'b0}}, // 31:1 - Unused
                        acc_done_i // 0 - acc_done
                    };
                    default: periph_i.data <= csr_set[periph_i.addr];
                endcase
                periph_i.data <= csr_set[periph_i.addr];
            end
        end
    end
end

// CSR Decode
always_comb begin : csrDecode

    // Trigger
    start_o = 0;
    if (handshake_success && periph_i.wen && periph_i.addr == CSR_REG_TRIGGER) begin
        start_o = periph_i.data[0];
    end

    // Config portions
    qracc_cfg = qracc_config_t'(csr_set[CSR_REG_CONFIG]);

end


endmodule