// Overall controller for QRAcc
// Microcode looper

import qracc_pkg::*;

module qracc_controller #(

    // Instmem
    parameter numScalers = 32,
    parameter numRows = 256,

    parameter internalInterfaceWidth = 128,
    parameter dataBusWidth = 32,

    parameter numBanks = 8,
    parameter numColsPerBank = 32,
    localparam internalInterfaceElements = internalInterfaceWidth / 8
) (
    input clk, nrst,

    qracc_ctrl_interface periph_i,
    qracc_data_interface bus_i,

    // Signals to the people
    output qracc_control_t ctrl_o,
    output to_sram_t to_sram,
    output logic [numBanks-1:0] bank_select,

    // Signals from the people
    input qracc_ready,
    input qracc_output_valid,
    input from_sram_t from_sram,
    input int_write_queue_valid,

    // Signals from csr
    input qracc_config_t cfg,
    input csr_main_clear,
    input qracc_trigger_t csr_main_trigger,
    input csr_main_busy,
    input csr_main_inst_write_mode,

    // Debugging
    output logic [31:0] debug_pc_o
);

///////////////////
// Parameters
///////////////////

parameter CSR_REGISTER_MAIN = 0;
parameter CSR_REGISTER_CONFIG = 1;
parameter CSR_REGISTER_STATUS = 2;

localparam addrBits = $clog2(numRows);
localparam bankCodeBits = numBanks > 1 ? $clog2(numBanks) : 1;

///////////////////
// Signals
///////////////////

// Handshake Signals
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

// Configuration Calculation signals
logic [31:0] n_elements_per_word;

// Ping pong tracking signals
logic [31:0] ofmap_start_addr;
logic [31:0] ifmap_start_addr;
logic [31:0] act_wr_ptr;
logic [31:0] act_rd_ptr;

// Convolution window tracking signals
logic [31:0] opix_pos_x;
logic [31:0] opix_pos_y;
logic [3:0] fy_ctr; // filter y
logic [31:0] current_read_addr; // filter x
logic [31:0] ofmap_offset_ptr;
logic window_data_valid_q;
logic actmem_wr_en;
logic feature_loader_valid_out_qq;
logic [31:0] feature_loader_addr_qq;
logic last_window;
logic [$clog2(numBanks)-1:0] bank_select_code;
logic write_queue_done;
logic int_write_queue_valid_q;
logic feature_loader_wr_en_d;

// Multicycle Activation Read
logic [9:0] read_set;
logic [9:0] num_read_sets;
assign num_read_sets = ( (cfg.num_input_channels*cfg.filter_size_x - 1) / internalInterfaceElements ) + 1;

// Write tracking signals
logic [31:0] scaler_ptr;
logic [31:0] weight_ptr;

///////////////////
// Logic
///////////////////

assign n_elements_per_word = dataBusWidth / { {28{1'b0}} ,cfg.n_input_bits_cfg};

typedef enum logic [3:0] {
    S_IDLE = 0,
    S_LOADACTS = 1,
    S_LOADSCALER = 2,
    S_LOADWEIGHTS = 3,
    S_COMPUTE_ANALOG = 4,
    S_READACTS = 5,
    S_LOADBIAS = 6,
    S_COMPUTE_DIGITAL = 7
} state_t;

state_t state_q;
state_t state_d;

always_ff @( posedge clk or negedge nrst ) begin : stateFlipFlop
    if (!nrst) begin
        state_q <= S_IDLE;
    end else begin
        state_q <= state_d;
    end
end

// Tracking queue emptiness
always_ff @( posedge clk or negedge nrst ) begin
    if (!nrst) begin
        write_queue_done <= 0;
        int_write_queue_valid_q <= int_write_queue_valid;
    end else begin
        int_write_queue_valid_q <= int_write_queue_valid;
        write_queue_done <= ~int_write_queue_valid && int_write_queue_valid_q; // 1->0 transition
    end
end

always_comb begin : ctrlDecode
    ctrl_o = 0; // must be that ctrl_o is a NOP
    to_sram.rq_wr_i = 0;
    to_sram.rq_valid_i = 0;
    to_sram.wr_data_i = 0;
    to_sram.addr_i = 0;
    bus_i.ready = 0;
    bus_i.rd_data_valid = 0;
    bank_select_code = 0;
    bank_select = 0;
    case(state_q)
        S_LOADWEIGHTS: begin
            to_sram.rq_wr_i = data_write;
            to_sram.rq_valid_i = bus_i.valid;
            to_sram.addr_i = weight_ptr[$clog2(numBanks)+:addrBits];
            to_sram.wr_data_i = bus_i.data_in;
            bus_i.ready = from_sram.rq_ready_o;
            bank_select_code = weight_ptr[bankCodeBits-1:0] - 1; // Delay by 1 cycle;
            bank_select = (numBanks > 1) ? (1 << bank_select_code) : 1;
        end
        S_LOADACTS: begin
            ctrl_o.activation_buffer_ext_wr_en = data_write;
            ctrl_o.activation_buffer_ext_wr_addr = act_wr_ptr;
            bus_i.ready = 1;
        end
        S_LOADSCALER: begin
            ctrl_o.output_scaler_scale_w_en = data_write;
            ctrl_o.output_scaler_shift_w_en = data_write;
            ctrl_o.output_scaler_offset_w_en = data_write;
            bus_i.ready = 1;
        end
        S_LOADBIAS: begin
            ctrl_o.output_bias_w_en = data_write;
            bus_i.ready = 1;
            // ctrl_o.activation_buffer_int_rd_en = (state_d == S_COMPUTE_ANALOG) ? 1 : 0;
        end
        S_COMPUTE_ANALOG: begin
                
            ctrl_o.activation_buffer_int_rd_addr = 
                    cfg.num_input_channels * cfg.input_fmap_dimx * (opix_pos_y * cfg.stride_y + {28'b0, fy_ctr})
                +   cfg.num_input_channels * opix_pos_x * cfg.stride_x 
                +   read_set*internalInterfaceElements // multicycle read if interface width < ifmap window row size
                ; // h*W*C + w*C + c
        
            ctrl_o.feature_loader_addr = feature_loader_addr_qq;
            // Do not write to feature loader seq_acc isn't ready yet
            ctrl_o.feature_loader_wr_en = ~(feature_loader_valid_out_qq && ~qracc_ready);
            // Latch output if feature loader isn't accepting writes
            ctrl_o.activation_buffer_int_rd_en = ctrl_o.feature_loader_wr_en; 
            ctrl_o.qracc_mac_data_valid = feature_loader_valid_out_qq;

            // OFMAP WRITEBACK
            ctrl_o.activation_buffer_int_wr_en = qracc_output_valid;
            ctrl_o.activation_buffer_int_wr_addr = ofmap_start_addr + ofmap_offset_ptr;
        end
        S_READACTS: begin
            ctrl_o.activation_buffer_ext_rd_en = 1;
            ctrl_o.activation_buffer_ext_rd_addr = act_rd_ptr + ofmap_start_addr;
            bus_i.rd_data_valid = 1;
        end
        default: begin
            ctrl_o = 0;
        end
    endcase
end

always_comb begin : stateDecode
    case(state_q)
        S_IDLE: begin
            case(csr_main_trigger)
                TRIGGER_IDLE: state_d = S_IDLE;
                TRIGGER_LOAD_ACTIVATION: state_d = S_LOADACTS;
                TRIGGER_LOADWEIGHTS_PERIPHS: state_d = S_LOADWEIGHTS;
                TRIGGER_COMPUTE_ANALOG: state_d = S_COMPUTE_ANALOG;
                TRIGGER_COMPUTE_DIGITAL: state_d = S_COMPUTE_DIGITAL;
                TRIGGER_READ_ACTIVATION: state_d = S_READACTS;
                default: state_d = S_IDLE;
            endcase
        end
        S_LOADWEIGHTS: begin
            if (weight_ptr < numRows*numBanks) begin
                state_d = S_LOADWEIGHTS;
            end else begin
                state_d = S_LOADSCALER;
            end
        end
        S_LOADACTS: begin
            if (act_wr_ptr + n_elements_per_word < cfg.input_fmap_size) begin
                state_d = S_LOADACTS;
            end else begin
                state_d = S_IDLE;
            end
        end
        S_LOADSCALER: begin
            // Scaler orchestrates its own address
            if (scaler_ptr < numScalers-1) begin
                state_d = S_LOADSCALER;
            end else begin
                state_d = S_LOADBIAS;
            end
        end
        S_LOADBIAS: begin
            // Scaler orchestrates its own address
            if (scaler_ptr < numScalers-1) begin
                state_d = S_LOADBIAS;
            end else begin
                state_d = S_IDLE;
            end
        end
        S_COMPUTE_ANALOG: begin
            if (~feature_loader_valid_out_qq && qracc_ready && write_queue_done && last_window) begin
                state_d = S_IDLE;
            end else begin
                state_d = S_COMPUTE_ANALOG;
            end
        end
        S_READACTS: begin
            if (act_rd_ptr == cfg.output_fmap_size - 1) begin
                state_d = S_IDLE;
            end else begin
                state_d = S_READACTS;
            end
        end
        default: state_d = state_q;
    endcase
end

always_ff @( posedge clk or negedge nrst ) begin
    if (!nrst) begin
        feature_loader_valid_out_qq <= 0;
        feature_loader_addr_qq <= 0;
    end else begin
        if (feature_loader_valid_out_qq && ~qracc_ready) begin
            // Stall the feature loader
            feature_loader_valid_out_qq <= feature_loader_valid_out_qq;
            feature_loader_addr_qq <= feature_loader_addr_qq;
        end else begin
            feature_loader_valid_out_qq <= window_data_valid_q;
            feature_loader_addr_qq <= fy_ctr*cfg.num_input_channels*cfg.filter_size_x
                                    + read_set*internalInterfaceElements + {22'b0, cfg.mapped_matrix_offset_y}; // multicycle read if interface width < ifmap window row size
        end
    end
end

always_ff @( posedge clk or negedge nrst ) begin : computeCycleCounter
    if (!nrst) begin
        opix_pos_x <= 0;
        opix_pos_y <= 0;
        fy_ctr <= 0;
        window_data_valid_q <= 0;
        last_window <= 0;
        ofmap_offset_ptr <= 0;
        read_set <= 0;
    end else begin

        if (csr_main_clear) begin
            opix_pos_x <= 0;
            opix_pos_y <= 0;
            fy_ctr <= 0;
            window_data_valid_q <= 0;
            last_window <= 0;
            ofmap_offset_ptr <= 0;
            read_set <= 0;
        end else
        
        if (state_q == S_COMPUTE_ANALOG) begin

            if (qracc_output_valid) begin
                ofmap_offset_ptr <=  ofmap_offset_ptr + { 22'b0 , cfg.num_output_channels};
            end

            if (last_window) begin
                if(ctrl_o.feature_loader_wr_en) window_data_valid_q <= 0;
            end else begin

            if ( 
                // (window_data_valid_q && !qracc_ready) 
                ~ctrl_o.activation_buffer_int_rd_en
                || (read_set < num_read_sets - 1)
            ) begin 
                // stall 
                if (~ctrl_o.activation_buffer_int_rd_en) begin
                    // skip is due to stall
                    read_set <= read_set;
                end else begin
                    // skip is due to read set
                    read_set <= read_set + 1;
                    window_data_valid_q <= 0;
                end
            end else begin
                read_set <= 0;
                if (fy_ctr < cfg.filter_size_y - 1) begin
                    fy_ctr <= fy_ctr + 1;
                    window_data_valid_q <= 0;
                end else begin
                    fy_ctr <= 0;

                    if (opix_pos_x == cfg.output_fmap_dimx - 1 && 
                        opix_pos_y == cfg.output_fmap_dimy - 1 &&
                        fy_ctr == cfg.filter_size_y - 1 && 
                        read_set == num_read_sets - 1)
                        last_window <= 1;
                    window_data_valid_q <= 1;

                    if (opix_pos_x < cfg.output_fmap_dimx - 1) begin
                        opix_pos_x <= opix_pos_x + 1;
                    end else begin
                        opix_pos_x <= 0;
                        if (opix_pos_y < cfg.output_fmap_dimy - 1) begin
                            opix_pos_y <= opix_pos_y + 1;
                        end else begin
                            opix_pos_y <= 0;
                        end
                    end
                end
            end end
        end else begin
            opix_pos_x <= 0;
            opix_pos_y <= 0;
            fy_ctr <= 0;
            window_data_valid_q <= 0;
            last_window <= 0;
            ofmap_offset_ptr <= 0;
        end
    end
end

// Weight control logic
always_ff @( posedge clk or negedge nrst ) begin : weightWriteLogic
    if (!nrst) begin
        weight_ptr <= 0;
    end else begin
        if (csr_main_clear) begin
            weight_ptr <= 0;
        end else
        if (state_q == S_LOADWEIGHTS) begin
            if (data_write) weight_ptr <= weight_ptr + 1;
            if (state_d != S_LOADWEIGHTS) begin 
                weight_ptr <= 0;
            end
        end
    end
end

// Activation read and write pointers logic (for streamin and streamout of activations)

always_ff @( posedge clk or negedge nrst ) begin : actBufferLogic
    if (!nrst) begin
        ofmap_start_addr <= 0;
        ifmap_start_addr <= 0;
        act_wr_ptr <= 0;
        act_rd_ptr <= 0;
    end else begin
        if (csr_main_clear) begin
            ofmap_start_addr <= 0;
            ifmap_start_addr <= 0;
            act_wr_ptr <= 0;
            act_rd_ptr <= 0;
        end else

        if (state_q == S_IDLE) begin
            if (state_d == S_LOADACTS) ifmap_start_addr <= 0;
        end

        if (state_q == S_LOADACTS) begin
            
            if (state_d != S_LOADACTS) begin 
                    act_wr_ptr <= 0;
                    ofmap_start_addr <= ifmap_start_addr + act_wr_ptr + n_elements_per_word;
            end else begin
                if (data_write) begin
                    act_wr_ptr <= act_wr_ptr + n_elements_per_word;
                end
            end

        end

        if (state_q == S_READACTS) begin

            if (data_read) act_rd_ptr <= act_rd_ptr + 1;

            if (state_d != S_READACTS) begin 
                act_rd_ptr <= 0;
            end
        end

        if (state_q == S_COMPUTE_ANALOG) begin

            if (state_d != S_COMPUTE_ANALOG) begin
                ifmap_start_addr <= ofmap_start_addr;
                ofmap_start_addr <= ofmap_start_addr + ofmap_offset_ptr + { 22'b0 , cfg.num_output_channels};
            end
        end

    end
end

// Scaler logic
always_ff @( posedge clk or negedge nrst ) begin : scalerLogic
    if (!nrst) begin
        scaler_ptr <= 0;
    end else begin
        if (csr_main_clear) begin
            scaler_ptr <= 0;
        end else
        if (state_q == S_LOADSCALER) begin
            if (data_write) scaler_ptr <= scaler_ptr + 1;
            if (state_d != S_LOADSCALER) begin 
                scaler_ptr <= 0;
            end
        end
        if (state_q == S_LOADBIAS) begin
            if (data_write) scaler_ptr <= scaler_ptr + 1;
            if (state_d != S_LOADBIAS) begin 
                scaler_ptr <= 0;
            end
        end
    end
end


endmodule