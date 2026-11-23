/* 
n-Bit input DNN accelerator
uses n cycles to complete an n-bit input mac
asdasd
*/

`ifdef QRACC_PARAMS_FILE
`include `QRACC_PARAMS_FILE
`else
`include "qracc_params_defaults.svh"
`endif

`timescale 1ns/1ps

import qracc_pkg::*;

module qr_acc_top #(

    //  Parameters: Interface
    parameter dataInterfaceSize = 32,
    parameter ctrlInterfaceSize = 32,
    parameter int hostBusBits = 32,

    //  Parameters: CSRs
    // parameter csrWidth = 32,
    // parameter numCsr = 4,

    //  Parameters: QRAcc
    parameter qrAccInputBits = qrAccMaxInputBits,
    parameter qrAccInputElements = 256,
    parameter qrAccOutputBits = 8,
    parameter qrAccOutputElements = 256,
    parameter qrAccAdcBits = 4,
    parameter qrAccAccumulatorBits = 24, // Internal parameter of seq acc
    parameter int numPlanes = 8,

    //  Parameters: Per Bank
    parameter numRows = 256,
    parameter numCols = 32,
    parameter numBanks = 256/numCols,
    parameter int numBeatRows = 4,

    //  Parameters: Global Buffer
    parameter globalBufferDepth = 2**8,
    parameter globalBufferExtInterfaceWidth = 32,
    parameter globalBufferIntInterfaceWidth = 256,
    parameter globalBufferAddrWidth = 32,
    parameter globalBufferDataSize = 8,          // Byte-Addressability

    // Parameters: Feature Loader
    parameter aflDimY = 128,
    parameter aflDimX = 6,
    parameter aflAddrWidth = 32,
    parameter featureLoaderNumElements = 9*32, // We need 32 windows for WSAcc

    // Parameters: WSAcc
    parameter wsAccNumPes = 32, // Number of PEs in WSAcc
    parameter wsAccWindowElements = 9, // Number of elements in the WSAcc window

    // Parameters: Addressing
    parameter csrBaseAddr = 32'h0000_0010, // Base address for CSR
    parameter accBaseAddr = 32'h0000_0100 // Base address for Accelerator
) (
    input clk, nrst,

    // Control Interface
    input bus_req_t bus_req_i,
    output bus_resp_t bus_resp_o,

    // Analog passthrough signals
    output to_analog_t to_analog [numPlanes-1:0],
    input from_analog_t from_analog [numPlanes-1:0],
    output [numBanks-1:0] bank_select

    // // CSR signals for testing for now
    // input qracc_config_t cfg,
    // input csr_main_clear,
    // output csr_main_busy,
    // input csr_main_inst_write_mode, // TODO: Remove?
    // input qracc_trigger_t csr_main_trigger,
    // output csr_main_internal_state
);


//-----------------------------------
// Signals
//-----------------------------------

// Signals : Control
qracc_config_t cfg;
qracc_control_t qracc_ctrl;
logic csr_main_clear;
logic csr_main_busy;
logic csr_main_inst_write_mode;
logic [3:0] csr_main_internal_state;
qracc_trigger_t csr_main_trigger;

// Bus signals
bus_resp_t csr_bus_resp;
bus_resp_t controller_bus_resp;

// Signals : QRAcc
logic [qrAccInputElements-1:0][qrAccInputBits-1:0] qracc_mac_data;
logic qracc_output_valid;
logic [qrAccOutputElements-1:0][qrAccAccumulatorBits-1:0] qracc_mac_output;
logic qracc_ready;

// SRAM Signals
logic to_sram_rq_wr;
logic to_sram_rq_valid;
logic [numBeatRows*numPlanes*numCols-1:0] to_sram_wr_data_ctl;
logic [numBeatRows*numPlanes*numCols-1:0] to_sram_wr_data;
logic [$clog2(numRows)-1:0] to_sram_addr;
logic [numBanks-1:0] legacy_bank_select;
logic from_sram_rq_ready;
logic from_sram_rd_valid;
logic [numCols-1:0] from_sram_rd_data;

// Host-bus row staging: assemble numPlanes*numCols-bit rows from hostBusBits-wide LOADs
logic [numPlanes*numCols-1:0] row_stage_q;
logic [numCols-1:0] legacy_wr_data;

// Controller-internal SRAM signals (muxed with staging logic at top level)
logic wr_ctrl_rq_wr;
logic wr_ctrl_rq_valid;
logic [$clog2(numRows)-1:0] wr_ctrl_addr;

// Signals : Activation Buffer
logic [globalBufferIntInterfaceWidth-1:0] activation_buffer_rd_data;
logic [globalBufferIntInterfaceWidth-1:0] activation_buffer_int_wr_data;
logic [globalBufferAddrWidth-1:0] activation_buffer_int_wr_addr;
logic int_write_queue_valid_out;
logic [globalBufferExtInterfaceWidth-1:0] abuf_rd_data;

// Signals: Feature Loader and Padder
logic [globalBufferIntInterfaceWidth-1:0] activation_buffer_rd_data_padded; 
logic [featureLoaderNumElements-1:0][qrAccInputBits-1:0] feature_loader_data_out;

`ifdef ACTMEM_DEBUG
// One $monitor stream for the WSAcc/ACTMEM handshake.  Filter the log by
// timestamp/state; this is cheaper than many separate displays.
always @(posedge clk) begin
    if (u_qracc_controller.state_q == 7)
        $monitor("[MON] t=%0t st=%0d opix=(%0d,%0d) fy=%0d rs=%0d nrs=%0d flv=%0d wdv=%0d wsdi=%0d wsov=%0d wr=%0d waddr=%0d ifmap=%0d ofmap=%0d res=%0d preserve=%0d",
                 $time, u_qracc_controller.state_q,
                 u_qracc_controller.opix_pos_x,
                 u_qracc_controller.opix_pos_y,
                 u_qracc_controller.fy_ctr,
                 u_qracc_controller.read_set,
                 u_qracc_controller.num_read_sets,
                 u_qracc_controller.feature_loader_valid_out_qq,
                 u_qracc_controller.window_data_valid_q,
                 qracc_ctrl.wsacc_data_i_valid,
                 wsacc_data_o_valid,
                 qracc_ctrl.activation_buffer_int_wr_en,
                 qracc_ctrl.activation_buffer_int_wr_addr,
                 u_qracc_controller.ifmap_start_addr,
                 u_qracc_controller.ofmap_start_addr,
                 u_qracc_controller.result_start_addr,
                 cfg.preserve_ifmap);
    else
        $monitoroff;
end
// Per-node WSAcc/ACTMEM transaction counts, printed when digital ends.
integer dbg_ws_i = 0, dbg_ws_o = 0, dbg_wr = 0;
logic dbg_dig_q;
always @(posedge clk) begin
    if (u_qracc_controller.state_q == 7) begin
        if (qracc_ctrl.wsacc_data_i_valid) dbg_ws_i <= dbg_ws_i + 1;
        if (wsacc_data_o_valid) dbg_ws_o <= dbg_ws_o + 1;
        if (qracc_ctrl.activation_buffer_int_wr_en) dbg_wr <= dbg_wr + 1;
    end
    if (dbg_dig_q && u_qracc_controller.state_q != 7)
        $display("[DBG wsacc-node] t=%0t in=%0d out=%0d wr=%0d ofmap=%0d preserve=%0d",
                 $time, dbg_ws_i, dbg_ws_o, dbg_wr,
                 u_qracc_controller.ofmap_start_addr, cfg.preserve_ifmap);
    if (u_qracc_controller.state_q != 7) begin
        dbg_ws_i <= 0; dbg_ws_o <= 0; dbg_wr <= 0;
    end
    dbg_dig_q <= (u_qracc_controller.state_q == 7);
end
`endif

// Signals: Output Scaler
logic [qrAccOutputElements-1:0][qrAccOutputBits-1:0] output_scaler_output;
logic [qrAccOutputElements-1:0][qrAccOutputBits-1:0] aligned_output_scaler_output;

logic csr_rd_data_valid;

logic wsacc_data_o_valid;
logic [wsAccNumPes-1:0][qrAccAccumulatorBits-1:0] wsacc_data_o;
logic [wsAccNumPes-1:0][wsAccWindowElements-1:0][qrAccInputBits-1:0] wsacc_data_i;

//-----------------------------------
// Modules
//-----------------------------------

qracc_csr #(
    .csrWidth                   (32),
    .numCsr                     (16),
    .CSR_BASE_ADDR              (csrBaseAddr) // Last hex is for CSR address
) u_csr (
    .clk                        (clk),
    .nrst                       (nrst),
    .bus_req_i                  (bus_req_i),
    .bus_resp_o                 (csr_bus_resp),
    .cfg_o                      (cfg),
    .csr_main_clear             (csr_main_clear),
    .csr_main_trigger           (csr_main_trigger),
    .csr_main_busy              (csr_main_busy),
    .csr_main_inst_write_mode   (csr_main_inst_write_mode),
    .csr_main_internal_state    (csr_main_internal_state),
    .csr_rd_data_valid_o        (csr_rd_data_valid)
);

qracc_controller #(
    .numScalers                 (qrAccOutputElements),
    .numRows                    (qrAccInputElements),
    .internalInterfaceWidth     (globalBufferIntInterfaceWidth),
    .numBanks                   (numBanks),
    .numPlanes                  (numPlanes)
) u_qracc_controller (
    .clk                        (clk),
    .nrst                       (nrst),

    .bus_req_i                  (bus_req_i),
    .bus_resp_o                 (controller_bus_resp),

    .ctrl_o                     (qracc_ctrl),
    .to_sram_rq_wr              (wr_ctrl_rq_wr),
    .to_sram_rq_valid           (wr_ctrl_rq_valid),
    .to_sram_wr_data            (legacy_wr_data),
    .to_sram_addr               (wr_ctrl_addr),
    .from_sram_rq_ready         (from_sram_rq_ready),
    .from_sram_rd_valid         (from_sram_rd_valid),
    .from_sram_rd_data          (from_sram_rd_data),
    .bank_select                (legacy_bank_select),

    .qracc_output_valid         (qracc_output_valid),
    .qracc_ready                (qracc_ready),
    .int_write_queue_valid      (int_write_queue_valid_out),
    .wsacc_output_valid         (wsacc_data_o_valid),

    .cfg                        (cfg),
    .csr_main_clear             (csr_main_clear),
    .csr_main_trigger           (csr_main_trigger),
    .csr_main_busy              (csr_main_busy),
    .csr_main_inst_write_mode   (csr_main_inst_write_mode),
    .csr_main_internal_state    (csr_main_internal_state),
    .csr_rd_data_valid          (csr_rd_data_valid),

    .debug_pc_o                 () 
);

// Main matrix multiplication

assign qracc_mac_data = feature_loader_data_out[qrAccInputElements-1:0]; // Use only the first qrAccInputElements elements

seq_acc #(
    .maxInputBits     (qrAccInputBits),
    .inputElements    (qrAccInputElements),
    .outputElements   (qrAccOutputElements),
    .numCols          (numCols), // per bank
    .adcBits          (qrAccAdcBits),
    .accumulatorBits  (qrAccAccumulatorBits)
) u_seq_acc (
    .clk            (clk),
    .nrst           (nrst),
    
    .cfg            (cfg),
    
    .mac_data_i     (qracc_mac_data),
    .mac_valid_i    (qracc_ctrl.qracc_mac_data_valid),
    .ready_o        (qracc_ready),
    .valid_o        (qracc_output_valid),
    .mac_data_o     (qracc_mac_output),
    
    // Passthrough Signals
    .to_analog_o    (to_analog),
    .from_analog_i  (from_analog),

    // SRAM
    .to_sram_rq_wr              (to_sram_rq_wr),
    .to_sram_rq_valid           (to_sram_rq_valid),
    .wr_bus_sel_i               ((cfg.weight_bits_cfg > 1) ? 2'd0 : cfg.wr_bus_sel),
    .to_sram_wr_data            (to_sram_wr_data_ctl),
    .to_sram_addr               (to_sram_addr),
    .from_sram_rq_ready         (from_sram_rq_ready),
    .from_sram_rd_valid         (from_sram_rd_valid),
    .from_sram_rd_data          (from_sram_rd_data)
);

// Multibit write window: DATA_WRITE_ADDR (0x100) .. 0x100 + 256 rows x 64 words - 1
// addr[2:0] = plane, addr[5:3] = bank, addr[13:6] = SRAM row (matrix row)
wire mb_mode = (cfg.weight_bits_cfg > 1);
wire mb_weight_load = wr_ctrl_rq_wr && mb_mode
    && (bus_req_i.addr >= 32'h00000100)
    && (bus_req_i.addr < 32'h00000100 + 32'd16384);

// Row staging: assemble numPlanes*numCols-bit rows from hostBusBits-wide LOADs
always_ff @(posedge clk or negedge nrst) begin : rowStageRegs
    if (!nrst) begin
        row_stage_q <= '0;
    end else begin
        if (mb_weight_load) begin
            int word_idx;
            word_idx = bus_req_i.addr[2:0];
            row_stage_q[word_idx*hostBusBits +: hostBusBits] <= bus_req_i.data_in;
        end
    end
end

// Row complete: last word of staged row
wire row_complete_pulse = mb_weight_load
    && bus_req_i.addr[2:0] == (numPlanes*numCols/hostBusBits - 1);

// Hold the target bank for the wr_controller write window (4 cycles per row)
logic [2:0] mb_wr_hold_q;
logic [$clog2(numBanks)-1:0] mb_bank_q;
always_ff @(posedge clk or negedge nrst) begin : mbWrHold
    if (!nrst) begin
        mb_wr_hold_q <= 0;
    end else if (row_complete_pulse) begin
        mb_wr_hold_q <= 3'd4;
        mb_bank_q <= bus_req_i.addr[5:3];
    end else if (mb_wr_hold_q != 0) begin
        mb_wr_hold_q <= mb_wr_hold_q - 1'b1;
    end
end
assign bank_select = (mb_wr_hold_q != 0) ? (numBanks'(1) << mb_bank_q) : legacy_bank_select;

// Complete row value including the current LOAD word (valid when row_complete_pulse)
logic [numPlanes*numCols-1:0] complete_row;
always_comb begin : completeRowComb
    complete_row = row_stage_q;
    if (row_complete_pulse)
        complete_row[bus_req_i.addr[2:0]*hostBusBits +: hostBusBits] = bus_req_i.data_in;
end

// SRAM write mux: staging logic overrides controller during multibit row writes
always_comb begin : sramWriteMux
    to_sram_rq_wr = wr_ctrl_rq_wr;
    to_sram_rq_valid = wr_ctrl_rq_valid;
    to_sram_addr = wr_ctrl_addr;
    to_sram_wr_data_ctl = '0;
    to_sram_wr_data_ctl[31:0] = legacy_wr_data;

    if (mb_weight_load) begin
        to_sram_rq_wr = 1'b0;
        to_sram_rq_valid = 1'b0;
    end

    if (mb_mode && row_complete_pulse) begin
        int row;
        row = (bus_req_i.addr - 32'h00000100) >> 6;
        to_sram_rq_wr = 1'b1;
        to_sram_rq_valid = 1'b1;
        to_sram_addr = row;
        to_sram_wr_data_ctl = '0;
        to_sram_wr_data_ctl[numPlanes*numCols-1:0] = complete_row;
    end
end

`ifdef DEBUG
integer dbg_mb_writes = 0;
integer dbg_mb_rows = 0;
always_ff @(posedge clk) begin
    if (bus_req_i.valid && bus_req_i.wen && bus_req_i.addr == 32'h00000017)
        $display("[DBG top] reg7 write seen at top data=%h cfg.weight_bits=%0d", bus_req_i.data_in, cfg.weight_bits_cfg);
    if (mb_weight_load) begin
        dbg_mb_writes <= dbg_mb_writes + 1;
        if (dbg_mb_writes < 6)
            $display("[DBG mb] addr=%h data=%h p=%0d k=%0d r=%0d", bus_req_i.addr, bus_req_i.data_in, bus_req_i.addr[2:0], bus_req_i.addr[5:3], (bus_req_i.addr - 32'h00000100) >> 6);
    end
    if (row_complete_pulse) begin
        dbg_mb_rows <= dbg_mb_rows + 1;
        if (bus_req_i.addr >= 32'h00003100 || bus_req_i.addr == 32'h000040FF)
            $display("[DBG mb] row complete addr=%h row=%0d bank=%0d ready=%0d wr_rq=%0d data_lo=%h rows=%0d writes=%0d", bus_req_i.addr, (bus_req_i.addr - 32'h00000100) >> 6, bus_req_i.addr[5:3], from_sram_rq_ready, wr_ctrl_rq_wr, complete_row[31:0], dbg_mb_rows + 1, dbg_mb_writes + 1);
    end
end
`endif

always_comb begin : wsAccDataOrientation
    // Orient the data for the WSAcc PE cluster
    for (int i = 0; i < wsAccNumPes; i++) begin // Channels
        for (int j = 0; j < wsAccWindowElements; j++) begin // Window
            wsacc_data_i[i][j] = feature_loader_data_out[i + j * cfg.num_input_channels];
        end
    end
end

logic wsacc_o_ready;
assign wsacc_o_ready = 1;

wsacc_pe_cluster #(
    .numPes(wsAccNumPes),
    .windowElements(wsAccWindowElements),
    .outputWidth(qrAccAccumulatorBits)
) u_wsacc (
    .clk(clk),
    .nrst(nrst),
    .data_i(wsacc_data_i),
    .data_i_valid(qracc_ctrl.wsacc_data_i_valid),
    .data_i_ready(), // wsacc_pe_cluster will never stall in this system i just added it for fun
    
    .weight_itf_i(bus_req_i.data_in),
    .weight_itf_i_valid(qracc_ctrl.wsacc_weight_itf_i_valid),
    .weight_writing_done(),

    .data_o(wsacc_data_o),
    .data_o_valid(wsacc_data_o_valid),
    .data_o_ready(wsacc_o_ready)
);

// Main feature map buffer
localparam oscalerOutputSize = qrAccOutputBits*qrAccOutputElements;
localparam oscalerExtendBits = globalBufferIntInterfaceWidth - oscalerOutputSize;
logic activation_buffer_wr_ready;

`ifdef MODEL_MEM
ram_2w2r #(
    .dataSize           (globalBufferDataSize),
    .depth              (globalBufferDepth),
    .addrWidth          (globalBufferAddrWidth),
    .interfaceWidth1    (globalBufferExtInterfaceWidth),
    .interfaceWidth2    (globalBufferIntInterfaceWidth)
) u_activation_buffer    (
    .clk                (clk),
    .nrst               (nrst),
    
    // External Interface
    .wr_data_1_i        (bus_req_i.data_in),
    .wr_en_1_i          (qracc_ctrl.activation_buffer_ext_wr_en),
    .wr_addr_1_i        (qracc_ctrl.activation_buffer_ext_wr_addr),
    .rd_data_1_o        (abuf_rd_data),
    .rd_addr_1_i        (qracc_ctrl.activation_buffer_ext_rd_addr),
    .rd_en_1_i          (qracc_ctrl.activation_buffer_ext_rd_en),

    // Internal Interface
    .wr_data_2_i       (activation_buffer_int_wr_data),
    .wr_en_2_i         (int_write_queue_valid_out),
    .wr_addr_2_i       (activation_buffer_int_wr_addr),
    .rd_data_2_o       (activation_buffer_rd_data),
    .rd_addr_2_i       (qracc_ctrl.activation_buffer_int_rd_addr),
    .rd_en_2_i         (qracc_ctrl.activation_buffer_int_rd_en)
);
assign activation_buffer_wr_ready = 1;
`else // MODEL_MEM
activation_buffer #(
    .dataSize           (globalBufferDataSize),
    .addrWidth          (globalBufferAddrWidth),
    .interfaceWidth1    (globalBufferExtInterfaceWidth),
    .interfaceWidth2    (globalBufferIntInterfaceWidth)
) u_activation_buffer (
    .clk                (clk),
    .nrst               (nrst),
    
    // External Interface
    .wr_data_1_i        (bus_req_i.data_in),
    .wr_en_1_i          (qracc_ctrl.activation_buffer_ext_wr_en),
    .wr_addr_1_i        (qracc_ctrl.activation_buffer_ext_wr_addr),
    .rd_data_1_o        (abuf_rd_data),
    .rd_addr_1_i        (qracc_ctrl.activation_buffer_ext_rd_addr),
    .rd_en_1_i          (qracc_ctrl.activation_buffer_ext_rd_en),

    // Internal Interface
    .wr_data_2_i       (activation_buffer_int_wr_data),
    .wr_en_2_i         (int_write_queue_valid_out),
    .wr_addr_2_i       (activation_buffer_int_wr_addr),
    .rd_data_2_o       (activation_buffer_rd_data),
    .rd_addr_2_i       (qracc_ctrl.activation_buffer_int_rd_addr),
    .rd_en_2_i         (qracc_ctrl.activation_buffer_int_rd_en),

    .wr_ready_o        (activation_buffer_wr_ready) // Ready signal for external interface
);
`endif // MODEL_MEM

// Padder - implements hardware padding
padder #(
    .elementWidth    (qrAccInputBits),
    .numElements     (globalBufferIntInterfaceWidth / qrAccInputBits)
) u_padder (
    .data_i          (activation_buffer_rd_data),           
    .pad_start       (qracc_ctrl.padding_start),        
    .pad_end         (qracc_ctrl.padding_end),          
    .pad_value       (cfg.padding_value),        
    .data_o          (activation_buffer_rd_data_padded)           
);

// Feature Loader - stages the input data for qrAcc
feature_loader #(
    .inputWidth        (globalBufferIntInterfaceWidth),
    .addrWidth         (aflAddrWidth),
    .elementWidth      (qrAccInputBits),
    .numElements       (featureLoaderNumElements)
) u_feature_loader (
    .clk               (clk),
    .nrst              (nrst),

    // Interface with buffer
    .addr_i            (qracc_ctrl.feature_loader_addr),  
    .data_i            (activation_buffer_rd_data_padded), // Padded data from activation buffer
    .wr_en             (qracc_ctrl.feature_loader_wr_en),  
    
    // Interface with QR accelerator
    .data_o            (feature_loader_data_out),

    .mask_start        (cfg.mapped_matrix_offset_y),
    .mask_end          (cfg.filter_size_y * cfg.filter_size_x * cfg.num_input_channels + cfg.mapped_matrix_offset_y)
);

logic [qrAccOutputElements-1:0][qrAccAccumulatorBits-1:0] oscaler_input;
always_comb begin : oscalerMux
    if (qracc_ctrl.wsacc_active) begin
        // Use WSAcc output if active
        oscaler_input = wsacc_data_o;
    end else begin
        // Use QRAcc output otherwise
        oscaler_input = qracc_mac_output;
    end
end

// Fixed point scaling from quantization methods in TFLite
output_scaler_set #(
    .numElements    (qrAccOutputElements),
    .inputWidth     (qrAccAccumulatorBits),
    .outputWidth    (qrAccOutputBits),
    .scaleBits      (16),
    .shiftBits      (4)
) u_output_scaler_set (
    .clk            (clk),
    .nrst           (nrst),
    
    .wx_i           (oscaler_input),
    .y_o            (output_scaler_output),

    .scale_w_en_i   (qracc_ctrl.output_scaler_scale_w_en),
    .scale_w_data_i (bus_req_i.data_in[4+:16]),

    .shift_w_en_i   (qracc_ctrl.output_scaler_shift_w_en),
    .shift_w_data_i (bus_req_i.data_in[3:0]),
    
    .offset_w_en_i   (qracc_ctrl.output_scaler_offset_w_en),
    .offset_w_data_i (bus_req_i.data_in[20+:8]),

    .bias_w_en_i    (qracc_ctrl.output_bias_w_en),
    .bias_w_data_i  (bus_req_i.data_in[31:0]),

    .cfg_unsigned   (cfg.unsigned_acts),
    .cfg_output_bits(cfg.n_output_bits_cfg)
);

mm_output_aligner #(
    .numColsPerBank (numCols),
    .elementBits    (qrAccOutputBits),
    .numElements    (qrAccOutputElements)
) u_mm_output_aligner (
    .data_i         (output_scaler_output),
    .cfg_i          (cfg),
    .data_o         (aligned_output_scaler_output)
);

logic [numBanks-1:0] piso_write_queue_valid_in;
logic [numBanks-1:0][globalBufferAddrWidth-1:0] piso_write_queue_addr_in;
always_comb begin
    piso_write_queue_valid_in = '0;
    piso_write_queue_addr_in = '0;
    for (int i = 0; i < numBanks; i++) begin
        piso_write_queue_valid_in[i] = qracc_ctrl.activation_buffer_int_wr_en && ( 
            ( cfg.num_output_channels > (numCols * i)) );
        piso_write_queue_addr_in[i] = qracc_ctrl.activation_buffer_int_wr_addr + (i * numCols);
    end
end

piso_write_queue #(
    .numParallelIn       (numBanks),
    .writeInterfaceWidth (globalBufferIntInterfaceWidth),
    .queueDepth          ( (qrAccOutputElements/numCols)*2 ), 
    .maxBits             (8),
    .writeAddrWidth      (globalBufferAddrWidth)
) u_piso_write_queue (
    .clk            (clk),
    .nrst           (nrst),

    .data_in        (aligned_output_scaler_output), // must always be equal to numBanks * oscalerOutputSize
    .addr_in        (piso_write_queue_addr_in),
    .valid_in       (piso_write_queue_valid_in),
    .ready_out      (activation_buffer_wr_ready),

    .addr_out       (activation_buffer_int_wr_addr), // Writing to internal interface
    .data_out       (activation_buffer_int_wr_data), // Writing to internal interface
    .valid_out      (int_write_queue_valid_out) // Valid signal for internal interface
);

// Manage bus output
always_comb begin : busOutputManage
    if ((bus_req_i.addr & 32'hFFFF_FFF0) == csrBaseAddr) begin
        // CSR Base Address
        bus_resp_o = csr_bus_resp;
    end else begin
        bus_resp_o = controller_bus_resp;
        bus_resp_o.data_out = abuf_rd_data; // Read from activation buffer
    end
end

`ifdef DEBUG
int dbg_top_cnt = 0;
always_ff @(posedge clk) if (qracc_output_valid && dbg_top_cnt < 2) begin
    dbg_top_cnt <= dbg_top_cnt + 1;
    $display("[DBG qr_acc_top] n=%0d oscaler_input[0]=%0d output_scaler_output[0]=%0d", dbg_top_cnt, oscaler_input[0], output_scaler_output[0]);
end
`endif

`ifdef ACTMEM_DEBUG
// Explicit ACTMEM handoff probe: node config, first internal writes, first
// feature-loader reads (post-padder) and their addresses.  Enable with
// +define+ACTMEM_DEBUG.
int dbg_act_wr = 0;
int dbg_act_rd = 0;
int dbg_fl = 0;
logic [15:0] dbg_prev_in = 16'hffff;
logic [15:0] dbg_prev_out = 16'hffff;
logic [3:0] dbg_prev_fx = 4'hf;
logic [3:0] dbg_prev_fy = 4'hf;
always_ff @(posedge clk) begin
    if (cfg.num_input_channels != dbg_prev_in
            || cfg.num_output_channels != dbg_prev_out
            || cfg.filter_size_x != dbg_prev_fx
            || cfg.filter_size_y != dbg_prev_fy) begin
        $display("[DBG actmem node] in=%0d out=%0d fx=%0d fy=%0d ifmap_start=%0d ofmap_start=%0d",
                 cfg.num_input_channels, cfg.num_output_channels,
                 cfg.filter_size_x, cfg.filter_size_y,
                 u_qracc_controller.ifmap_start_addr,
                 u_qracc_controller.ofmap_start_addr);
        dbg_prev_in <= cfg.num_input_channels;
        dbg_prev_out <= cfg.num_output_channels;
        dbg_prev_fx <= cfg.filter_size_x;
        dbg_prev_fy <= cfg.filter_size_y;
        dbg_act_wr <= 0;
        dbg_act_rd <= 0;
        dbg_fl <= 0;
    end
    if (int_write_queue_valid_out && dbg_act_wr < 4) begin
        $display("[DBG actwr] n=%0d addr=%0d data=%h",
                 dbg_act_wr, activation_buffer_int_wr_addr,
                 activation_buffer_int_wr_data);
        dbg_act_wr <= dbg_act_wr + 1;
    end
    if (qracc_ctrl.activation_buffer_int_rd_en && dbg_act_rd < 4) begin
        $display("[DBG actrd] n=%0d addr=%0d fl_addr=%0d data=%h",
                 dbg_act_rd, qracc_ctrl.activation_buffer_int_rd_addr,
                 qracc_ctrl.feature_loader_addr, activation_buffer_rd_data);
        dbg_act_rd <= dbg_act_rd + 1;
    end
    if (qracc_ctrl.feature_loader_wr_en && dbg_fl < 4) begin
        $display("[DBG flwr] n=%0d addr=%0d data=%h",
                 dbg_fl, qracc_ctrl.feature_loader_addr,
                 activation_buffer_rd_data_padded);
        dbg_fl <= dbg_fl + 1;
    end
end
`endif

endmodule