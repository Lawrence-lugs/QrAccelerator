// CSR Implementation inspired by sir Ry

import qracc_pkg::*;
module qracc_csr #(
    parameter csrWidth = 32,
    parameter numCsr = 16,
    parameter CSR_BASE_ADDR = 32'h0000_0010 // Last hex is for CSR address
) (
    input clk, nrst,

    input bus_req_t bus_req_i,
    output bus_resp_t bus_resp_o,
    output logic csr_rd_data_valid_o,

    // CSR signals
    output qracc_config_t cfg_o,
    output logic csr_main_clear,
    output qracc_trigger_t csr_main_trigger,
    input csr_main_busy,
    output logic csr_main_inst_write_mode,
    input [3:0] csr_main_internal_state
);

// Parameters
localparam CSR_BASE_MASK = 32'hFFFF_FFF0; // Mask for base address
typedef enum logic [3:0] { 
    CSR_REG_MAIN = 0,
    CSR_REG_CONFIG = 1,
    CSR_REG_IFMAP_DIMS = 2,
    CSR_REG_OFMAP_DIMS = 3,
    CSR_REG_CHANNELS = 4,
    CSR_REG_OFFSETS = 5,
    CSR_REG_PADDING = 6
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
    kausap_ako = (bus_req_i.addr & CSR_BASE_MASK) == CSR_BASE_ADDR;
    handshake_success = bus_req_i.valid && kausap_ako; 
    csr_addr = bus_req_i.addr[3:0]; // Extracting the lower 4 bits for CSR address
    bus_resp_o.ready = 1; // The CSR is always ready to respond
end

// CSR Write & Reads
always_ff @( posedge clk or negedge nrst ) begin : csrWriteReads
    if (!nrst) begin
        for(int i = 0; i < numCsr; i++) begin
            csr_set[i] <= 0;
        end
        bus_resp_o.rd_data_valid <= 1'b0;
    end else begin
        if (handshake_success) begin
            // Write to CSR
            if (bus_req_i.wen) begin
                csr_set[csr_addr] <= bus_req_i.data_in;
                bus_resp_o.rd_data_valid <= 1'b0;
            end else begin
                case (csr_addr)
                    CSR_REG_MAIN: begin
                        // $display("CSR_REG_MAIN: csr_main_read_output = %h", csr_main_read_output);
                        bus_resp_o.data_out <= csr_main_read_output;
                        bus_resp_o.rd_data_valid <= 1'b1;
                    end
                    default: begin
                        bus_resp_o.data_out <= csr_set[csr_addr]; 
                        bus_resp_o.rd_data_valid <= 1'b1;
                    end
                endcase
            end
        end else begin
            bus_resp_o.data_out <= 32'b0; // Default value when not addressed
        end
    end
end

// CSR Decode
always_comb begin : csrDecode
    csr_main_read_output = {
        19'b0, // free
        1'b0, // preserve_ifmap
        csr_main_internal_state,
        3'b0, // free
        csr_main_busy, // csr_main_busy
        1'b0, // csr_main_clear
        3'b0 // csr_main_trigger
    };

    // When the bus is trying to write to main, pass it combinationally...
    if (handshake_success && bus_req_i.wen && (csr_addr == CSR_REG_MAIN)) begin
        csr_main_trigger = qracc_trigger_t'(bus_req_i.data_in[2:0]);
        csr_main_clear = bus_req_i.data_in[3]; 
        csr_main_inst_write_mode = bus_req_i.data_in[5];
    end else begin
        csr_main_trigger = TRIGGER_IDLE;
        csr_main_clear = 1'b0;
        csr_main_inst_write_mode = 1'b0;
    end

    // Assign configuration output
    cfg_o.preserve_ifmap = csr_set[CSR_REG_MAIN][12];

    cfg_o.binary_cfg           = csr_set[CSR_REG_CONFIG][0];
    cfg_o.unsigned_acts        = csr_set[CSR_REG_CONFIG][1];
    cfg_o.adc_ref_range_shifts = csr_set[CSR_REG_CONFIG][7:4];
    cfg_o.filter_size_y        = csr_set[CSR_REG_CONFIG][11:8];
    cfg_o.filter_size_x        = csr_set[CSR_REG_CONFIG][15:12];
    cfg_o.stride_x             = csr_set[CSR_REG_CONFIG][19:16];
    cfg_o.stride_y             = csr_set[CSR_REG_CONFIG][23:20];
    cfg_o.n_input_bits_cfg     = csr_set[CSR_REG_CONFIG][27:24];
    cfg_o.n_output_bits_cfg    = csr_set[CSR_REG_CONFIG][31:28];

    cfg_o.input_fmap_dimx = csr_set[CSR_REG_IFMAP_DIMS][15:0];
    cfg_o.input_fmap_dimy = csr_set[CSR_REG_IFMAP_DIMS][31:16];

    cfg_o.output_fmap_dimx = csr_set[CSR_REG_OFMAP_DIMS][15:0];
    cfg_o.output_fmap_dimy = csr_set[CSR_REG_OFMAP_DIMS][31:16];

    cfg_o.num_input_channels  = csr_set[CSR_REG_CHANNELS][15:0];
    cfg_o.num_output_channels = csr_set[CSR_REG_CHANNELS][31:16];

    cfg_o.mapped_matrix_offset_x = csr_set[CSR_REG_OFFSETS][15:0];
    cfg_o.mapped_matrix_offset_y = csr_set[CSR_REG_OFFSETS][31:16];

    cfg_o.padding       = csr_set[CSR_REG_PADDING][3:0];
    cfg_o.padding_value = csr_set[CSR_REG_PADDING][11:4];
end

endmodule