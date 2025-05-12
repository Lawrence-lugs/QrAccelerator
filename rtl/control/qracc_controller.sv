// Overall controller for QRAcc
// Microcode looper

import qracc_pkg::*;

module qracc_controller #(

    // Instmem
    parameter numScalers = 32,
    parameter numRows = 256,

    parameter internalInterfaceWidth = 128,
    parameter dataBusWidth = 32,

    parameter numBanks = 8

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

    // Signals from csr
    input qracc_config_t cfg,
    input csr_main_clear,
    input csr_main_start,
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
logic window_data_valid;
logic actmem_wr_en;
logic window_data_valid_qq;
logic [31:0] feature_loader_addr_qq;
logic compute_stall;
logic send_last_opix;
logic compute_last_opix;
logic [$clog2(numBanks)-1:0] bank_select_code;

// Write tracking signals
logic [31:0] scaler_ptr;
logic [31:0] weight_ptr;

///////////////////
// Modules
///////////////////

///////////////////
// Logic
///////////////////

// Control signals decode
// parameter S_IDLE = 4'b0000;
// parameter S_LOADACTS = 4'b0001;
// parameter S_LOADSCALER = 4'b0010;
// parameter S_LOADWEIGHTS = 4'b0011;
// parameter S_COMPUTE = 4'b0100;
// parameter S_READACTS = 4'b0101;

assign n_elements_per_word = dataBusWidth / { {28{1'b0}} ,cfg.n_input_bits_cfg};

typedef enum logic [3:0] {
    S_IDLE = 0,
    S_LOADACTS = 1,
    S_LOADSCALER = 2,
    S_LOADWEIGHTS = 3,
    S_COMPUTE = 4,
    S_READACTS = 5,
    S_LOADBIAS = 6
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
        end
        S_COMPUTE: begin
            ctrl_o.qracc_mac_data_valid = window_data_valid_qq;
            
            // IFMAP READ
            // ctrl_o.activation_buffer_int_rd_addr = 
            //     cfg.num_input_channels * ( opix_pos_x + 
            //     cfg.input_fmap_dimx * (opix_pos_y + {28'b0, fy_ctr}) ); // ifmap_addr = c + x*C + (y + fy)*C*OX, but c is always 0.
                
            ctrl_o.activation_buffer_int_rd_addr = 
                    cfg.num_input_channels * cfg.input_fmap_dimx * (opix_pos_y + {28'b0, fy_ctr})
                +   cfg.num_input_channels * opix_pos_x
                ; // h*W*C + w*C + c

            ctrl_o.activation_buffer_int_rd_en = 1;

            // WINDOW LOAD
            // window_data_valid_qq && window_data_valid indicates an active stall
            ctrl_o.feature_loader_wr_en = ! (window_data_valid_qq && window_data_valid);
            ctrl_o.feature_loader_addr = feature_loader_addr_qq; // FX*C*fy

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
            if (csr_main_start) begin
                state_d = S_LOADWEIGHTS;
            end else begin
                state_d = S_IDLE;
            end
        end
        S_LOADWEIGHTS: begin
            if (weight_ptr < numRows*numBanks) begin
                state_d = S_LOADWEIGHTS;
            end else begin
                state_d = S_LOADACTS;
            end
        end
        S_LOADACTS: begin
            if (act_wr_ptr + n_elements_per_word < cfg.input_fmap_size) begin
                state_d = S_LOADACTS;
            end else begin
                state_d = S_LOADSCALER;
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
                state_d = S_COMPUTE;
            end
        end
        S_COMPUTE: begin
            if (compute_last_opix && qracc_output_valid) begin
                state_d = S_READACTS;
            end else begin
                state_d = S_COMPUTE;
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

// Convolution output tracking counter

assign compute_stall = (state_q == S_COMPUTE) && (window_data_valid && !qracc_ready);

always_ff @( posedge clk or negedge nrst ) begin
    if (!nrst) begin
        window_data_valid_qq <= 0;
        feature_loader_addr_qq <= 0;
    end else begin
        window_data_valid_qq <= window_data_valid;
        feature_loader_addr_qq <= fy_ctr*cfg.num_input_channels*cfg.filter_size_x;
    end
end

always_ff @( posedge clk or negedge nrst ) begin : computeCycleCounter
    if (!nrst) begin
        opix_pos_x <= 0;
        opix_pos_y <= 0;
        fy_ctr <= 0;
        window_data_valid <= 0;
        send_last_opix <= 0;
        compute_last_opix <= 0;
        ofmap_offset_ptr <= 0;
    end else begin

        if (csr_main_clear) begin
            opix_pos_x <= 0;
            opix_pos_y <= 0;
            fy_ctr <= 0;
            window_data_valid <= 0;
            send_last_opix <= 0;
            compute_last_opix <= 0;
            ofmap_offset_ptr <= 0;
        end else
        
        if (state_q == S_COMPUTE) begin

            if (opix_pos_x == cfg.output_fmap_dimx - 1 && 
                opix_pos_y == cfg.output_fmap_dimy - 1 &&
                fy_ctr == cfg.filter_size_y - 1 && qracc_output_valid)
                send_last_opix <= 1;

            // This thing would break if inputBits is small enough that 
            if(qracc_output_valid & send_last_opix) begin
                compute_last_opix <= 1;
            end

            // Ofmap writes strided by C
            if (qracc_output_valid) begin
                ofmap_offset_ptr <=  ofmap_offset_ptr + { 22'b0 , cfg.num_output_channels};
            end

            if ( (window_data_valid && !qracc_ready) || send_last_opix || compute_last_opix ) begin 
                // stall 
                if (compute_last_opix) begin
                    window_data_valid <= 0;
                end
            end else

            if (fy_ctr < cfg.filter_size_y - 1) begin
                fy_ctr <= fy_ctr + 1;
                window_data_valid <= 0;
            end else begin
                fy_ctr <= 0;
                window_data_valid <= 1;

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
        end else begin
            opix_pos_x <= 0;
            opix_pos_y <= 0;
            fy_ctr <= 0;
            window_data_valid <= 0;
            send_last_opix <= 0;
            ofmap_offset_ptr <= 0;
            compute_last_opix <= 0;
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

        if (state_q == S_COMPUTE) begin

            if (state_d != S_COMPUTE) begin
                ifmap_start_addr <= ofmap_start_addr + ofmap_offset_ptr;
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