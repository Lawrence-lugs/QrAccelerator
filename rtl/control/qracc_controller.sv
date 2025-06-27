// Overall controller for QRAcc
// Microcode looper

import qracc_pkg::*;

module qracc_controller #(
    parameter numScalers = 32,
    parameter numRows = 256,
    parameter numWsAccWrites = 72, // 32 * 9 / 4
    // numWsAccWrites changes with the number of channels in a non-analytic way because of the 4-bit packing
    // but it remains the same for a specific hardware configuration

    parameter internalInterfaceWidth = 128,
    parameter dataBusWidth = 32,

    parameter numBanks = 8,
    parameter numColsPerBank = 32,
    localparam internalInterfaceElements = internalInterfaceWidth / 8
) (
    input clk, nrst,

    qracc_data_interface bus_i,

    // Signals to the people
    output qracc_control_t ctrl_o,
    output to_sram_t to_sram,
    output logic [numBanks-1:0] bank_select,

    // Signals from the people
    input qracc_ready,
    input qracc_output_valid,
    input wsacc_output_valid,
    input from_sram_t from_sram,
    input int_write_queue_valid,

    // Signals from csr
    input qracc_config_t cfg,
    input csr_main_clear,
    input qracc_trigger_t csr_main_trigger,
    input csr_main_inst_write_mode,
    output logic csr_main_busy,
    output logic [3:0] csr_main_internal_state,
    input csr_rd_data_valid,

    // Debugging
    output logic [31:0] debug_pc_o
);

///////////////////
// Parameters
///////////////////

localparam addrBits = $clog2(numRows);
localparam bankCodeBits = numBanks > 1 ? $clog2(numBanks) : 1;

///////////////////
// Signals
///////////////////

// Derived Layer Parameters
logic [31:0] input_fmap_size;
assign input_fmap_size = cfg.input_fmap_dimx * cfg.input_fmap_dimy * cfg.num_input_channels;
logic [31:0] output_fmap_size;
assign output_fmap_size = cfg.output_fmap_dimx * cfg.output_fmap_dimy * cfg.num_output_channels;

// Handshake Signalsl
logic data_handshake;
logic data_read;
logic data_write;
assign data_handshake = bus_i.valid && bus_i.ready;
assign data_read      = data_handshake && !bus_i.wen;
assign data_write     = data_handshake && bus_i.wen;

// Configuration Calculation signals
logic [31:0] n_elements_per_word;
assign n_elements_per_word = dataBusWidth / { {28{1'b0}} ,cfg.n_input_bits_cfg};

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
logic [31:0] read_set;
logic [31:0] num_read_sets;
assign num_read_sets = ( (cfg.num_input_channels*cfg.filter_size_x - 1) / internalInterfaceElements ) + 1;
logic read_acts_out_valid;

// Write tracking signals
logic [31:0] scaler_ptr;
logic [31:0] weight_ptr;

// Padding
logic [31:0] padding_address_offset;
logic [15:0] padding_start_q;
logic [15:0] padding_end_q;

///////////////////
// Logic
///////////////////


typedef enum logic [3:0] {
    S_IDLE = 0,
    S_LOADACTS = 1,
    S_LOADSCALER = 2,
    S_LOADWEIGHTS = 3,
    S_COMPUTE_ANALOG = 4,
    S_READACTS = 5,
    S_LOADBIAS = 6,
    S_COMPUTE_DIGITAL = 7,
    S_LOAD_DIGITAL_WEIGHTS = 8
} state_t;

state_t state_q;
state_t state_d;
state_t state_trigger;
assign csr_main_internal_state = state_q;

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
    csr_main_busy = ~( state_q == S_IDLE );
    case(state_q)
        S_IDLE: begin
            bus_i.ready = 1; // CSR is always ready to take data
            bus_i.rd_data_valid = csr_rd_data_valid;
        end
        S_LOADWEIGHTS: begin
            to_sram.rq_wr_i = data_write;
            to_sram.rq_valid_i = bus_i.valid;
            to_sram.addr_i = weight_ptr[$clog2(numBanks)+:addrBits];
            to_sram.wr_data_i = bus_i.data_in;
            bus_i.ready = from_sram.rq_ready_o;
            bank_select_code = weight_ptr[bankCodeBits-1:0] - 1; // Delay by 1 cycle;
            bank_select = (numBanks > 1) ? (1 << bank_select_code) : 1;
        end
        S_LOAD_DIGITAL_WEIGHTS: begin
            ctrl_o.wsacc_weight_itf_i_valid = bus_i.valid;
            bus_i.ready = 1;
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
        S_COMPUTE_ANALOG, S_COMPUTE_DIGITAL: begin

            if (state_q == S_COMPUTE_DIGITAL) ctrl_o.wsacc_active = 1;

            bus_i.ready = 1; // Ready to be read (all extern WRENs are deasserted)
                
            ctrl_o.activation_buffer_int_rd_addr = 
                    cfg.num_input_channels * 
                    cfg.input_fmap_dimx * 
                    ( (opix_pos_y*cfg.stride_y - {28'b0,cfg.padding}) + {28'b0, fy_ctr})
                +   cfg.num_input_channels * 
                    (opix_pos_x*cfg.stride_x - {28'b0,cfg.padding}) 
                +   read_set*internalInterfaceElements
                ; // h*W*C + w*C + c
            
            ctrl_o.feature_loader_addr = feature_loader_addr_qq;
            // Do not write to feature loader seq_acc isn't ready yet
            ctrl_o.feature_loader_wr_en = ~(feature_loader_valid_out_qq && ~qracc_ready);
            // Latch output if feature loader isn't accepting writes
            ctrl_o.activation_buffer_int_rd_en = ctrl_o.feature_loader_wr_en; 
            ctrl_o.qracc_mac_data_valid = feature_loader_valid_out_qq && (state_q == S_COMPUTE_ANALOG);
            ctrl_o.wsacc_data_i_valid = feature_loader_valid_out_qq && (state_q == S_COMPUTE_DIGITAL);

            // OFMAP WRITEBACK
            ctrl_o.activation_buffer_int_wr_en = qracc_output_valid || wsacc_output_valid;
            ctrl_o.activation_buffer_int_wr_addr = ofmap_start_addr + ofmap_offset_ptr;

            ctrl_o.padding_start = padding_start_q;
            ctrl_o.padding_end = padding_end_q;
        end
        S_READACTS: begin
            bus_i.ready = 1;
            ctrl_o.activation_buffer_ext_rd_en = 1;
            // Due to the ifmap->ofmap swapping, the ofmap is now in the ifmap_start_addr
            ctrl_o.activation_buffer_ext_rd_addr = act_rd_ptr + ifmap_start_addr;
            bus_i.rd_data_valid = read_acts_out_valid;
        end
        default: begin
            ctrl_o = 0;
        end
    endcase
end

always_comb begin : stateDecode
    case(csr_main_trigger)
        TRIGGER_IDLE               : state_trigger = S_IDLE;
        TRIGGER_LOAD_ACTIVATION    : state_trigger = S_LOADACTS;
        TRIGGER_LOADWEIGHTS        : state_trigger = S_LOADWEIGHTS;
        TRIGGER_COMPUTE_ANALOG     : state_trigger = S_COMPUTE_ANALOG;
        TRIGGER_COMPUTE_DIGITAL    : state_trigger = S_COMPUTE_DIGITAL;
        TRIGGER_READ_ACTIVATION    : state_trigger = S_READACTS;
        TRIGGER_LOADWEIGHTS_DIGITAL: state_trigger = S_LOAD_DIGITAL_WEIGHTS;
        TRIGGER_LOAD_SCALER        : state_trigger = S_LOADSCALER;
        default                    : state_trigger = S_IDLE;
    endcase
    case(state_q)
        S_IDLE: begin
            state_d = state_trigger;
        end
        S_LOADWEIGHTS: begin
            if (weight_ptr < numRows*numBanks) begin
                state_d = S_LOADWEIGHTS;
            end else begin
                state_d = S_IDLE;
            end
        end
        S_LOAD_DIGITAL_WEIGHTS: begin
            if (weight_ptr < numWsAccWrites-1) begin
                state_d = S_LOAD_DIGITAL_WEIGHTS;
            end else begin
                state_d = state_trigger;
            end
        end
        S_LOADACTS: begin
            if (act_wr_ptr + n_elements_per_word < input_fmap_size) begin
                state_d = S_LOADACTS;
            end else begin
                state_d = state_trigger;
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
                state_d = state_trigger;
            end
        end
        S_COMPUTE_DIGITAL: begin
            if (~feature_loader_valid_out_qq && write_queue_done && last_window) begin
                state_d = state_trigger;
            end else begin
                state_d = state_q;
            end
        end
        S_COMPUTE_ANALOG: begin
            if (~feature_loader_valid_out_qq && qracc_ready && write_queue_done && last_window) begin
                state_d = state_trigger;
            end else begin
                state_d = state_q;
            end
        end
        S_READACTS: begin
            if (act_rd_ptr > output_fmap_size - 1) begin
                state_d = state_trigger;
            end else begin
                state_d = S_READACTS;
            end
        end
        default: state_d = state_q;
    endcase
end

always_ff @( posedge clk or negedge nrst ) begin : paddingLogic
    
    if (!nrst) begin
        padding_start_q <= 0;
        padding_end_q <= 0;
    end else begin
        if (csr_main_clear) begin
            padding_start_q <= 0;
            padding_end_q <= 0;
        end else begin
            if (feature_loader_valid_out_qq && ~qracc_ready) begin
                // Stop for stalls
                padding_start_q <= padding_start_q;
                padding_end_q <= padding_end_q;
            end else 
            if (cfg.padding > 0) begin
                // For Y padding cases, pad all read sets
                if (opix_pos_y*cfg.stride_y + 32'(fy_ctr) == 0) begin
                    padding_start_q <= 0;
                    padding_end_q <= cfg.num_input_channels * cfg.filter_size_x;
                end else
                // We only start padding when OY + FY == 18 - 1 (because padding adds 2 rows)
                if (opix_pos_y*cfg.stride_y + 32'(fy_ctr) == 32'(cfg.input_fmap_dimy + 16'b1)) begin
                    padding_start_q <= 0;
                    padding_end_q <= cfg.num_input_channels * cfg.filter_size_x; 
                end else
                if (opix_pos_x == 0) begin
                    // Pad first pixel for all windows
                    // If a single read set is larger than the number of input channels, pad the entire read until the remainder is less than a read set count
                    if ( cfg.num_input_channels < read_set*internalInterfaceElements ) begin
                        // Don't pad anything- the current read set is past a single pixel
                        padding_start_q <= 0;
                        padding_end_q <= 0;
                    end else begin
                        // Pad all or up to the remaining channels of the pixel
                        padding_start_q <= 0;
                        padding_end_q <= (cfg.num_input_channels - read_set*internalInterfaceElements);
                    end
                    // padding_start_q <= 0;
                    // padding_end_q <= cfg.num_input_channels;
                end else
                if (opix_pos_x*cfg.stride_x == 32'(cfg.input_fmap_dimx - 16'b1)) begin
                    // Pad last pixel for all windows

                    if ( cfg.num_input_channels * (cfg.filter_size_x-4'b1) >=
                        (read_set+1)*internalInterfaceElements) begin
                        // CFx - C > (R_s+1)*W
                        // Don't pad anything- the end of current read set is before the padded region
                        padding_start_q <= 0;
                        padding_end_q <= 0;
                    end else
                    if ( cfg.num_input_channels * (cfg.filter_size_x-4'b1) < 
                        (read_set+1)*internalInterfaceElements ) begin
                        // CFx - C < R_s*w
                        // The end of read set is inside padded region
                        // Start = CFx-C-RsW see Journal 6 June 2025
                        // End = pad to end
                        padding_start_q <= ( cfg.num_input_channels * (cfg.filter_size_x-4'b1) ) - read_set*internalInterfaceElements; 
                        padding_end_q <= internalInterfaceElements;
                    end else 
                    begin
                        // Pad entire thing once we're past the padding point
                        padding_start_q <= 0;
                        padding_end_q <= internalInterfaceElements;
                    end
                    
                    // padding_start_q <= cfg.num_input_channels * 16'(cfg.filter_size_x - 4'b1);
                    // padding_end_q <= cfg.num_input_channels * cfg.filter_size_x;
                end else begin
                    // No padding
                    padding_start_q <= 0;
                    padding_end_q <= 0;
                end
            end
        end
    end
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
                                    + read_set*internalInterfaceElements 
                                    + {16'b0, cfg.mapped_matrix_offset_y}; // multicycle read if interface width < ifmap window row size
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
        
        if (state_q == S_COMPUTE_ANALOG || state_q == S_COMPUTE_DIGITAL) begin

            if (qracc_output_valid || wsacc_output_valid) begin
                ofmap_offset_ptr <=  ofmap_offset_ptr + { 16'b0 , cfg.num_output_channels};
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

                    if (opix_pos_x == 32'(cfg.output_fmap_dimx) - 1 && 
                        opix_pos_y == 32'(cfg.output_fmap_dimy) - 1 &&
                        fy_ctr == cfg.filter_size_y - 1 && 
                        read_set == num_read_sets - 1)
                        last_window <= 1;
                    window_data_valid_q <= 1;

                        opix_pos_x <= opix_pos_x + 1;
                    if (opix_pos_x < 32'(cfg.output_fmap_dimx) - 1) begin
                    end else begin
                        opix_pos_x <= 0;
                        if (opix_pos_y < 32'(cfg.output_fmap_dimy) - 1) begin
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
        if (state_q == S_LOAD_DIGITAL_WEIGHTS) begin
            if (bus_i.valid) weight_ptr <= weight_ptr + 1;
            if (state_d != S_LOAD_DIGITAL_WEIGHTS) begin 
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
        read_acts_out_valid <= 0;
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

            if (data_read) begin
                act_rd_ptr <= act_rd_ptr + 4;
                read_acts_out_valid <= 1;
            end

            if (state_d != S_READACTS) begin 
                act_rd_ptr <= 0;
                read_acts_out_valid <= 0;
            end
        end

        if (state_q == S_COMPUTE_ANALOG) begin
            if (state_d != S_COMPUTE_ANALOG) begin
                if (!cfg.preserve_ifmap) begin
                    ifmap_start_addr <= ofmap_start_addr;
                    ofmap_start_addr <= ofmap_start_addr + ofmap_offset_ptr + { 16'b0 , cfg.num_output_channels};
                end
            end
        end

        if (state_q == S_COMPUTE_DIGITAL) begin
            if (state_d != S_COMPUTE_DIGITAL) begin
                if (!cfg.preserve_ifmap) begin
                    ifmap_start_addr <= ofmap_start_addr;
                    ofmap_start_addr <= ofmap_start_addr + ofmap_offset_ptr + { 16'b0 , cfg.num_output_channels};
                end            
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