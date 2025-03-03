
// Write Controller Interface
// This module controls writes and reads to a C3SRAM array
// 
// To write:
// 1. Wait for ready to be high
// 2. Assert write_i and set addr_i to target row
// 3. Wait for done to be asserted
//
// To read:
// 1. Wait for ready to be high
// 2. Assert read_i and set addr_i to target row
// 3. Wait for done to be asserted
//
// Note: write_i and read_i should not be asserted simultaneously

module wr_controller #(
    parameter int numRows = 128,
    parameter int numCols = 32
) (
    input clk,
    input nrst,

    // we don't passively read in the interest of energy
    input write_i,
    input read_i,
    input [$clog2(numRows)-1:0] addr_i,
    input [numCols-1:0] wr_data_i,

    output logic done, //asserted for just 1 CC
    output logic ready,
    output logic [numCols-1:0] wr_data_q,

    // writes and reads
    output logic [numCols-1:0] c3sram_csel_o,
    output logic c3sram_saen_o,
    output logic c3sram_w2b_o,
    output logic c3sram_nprecharge_o,
    output logic [numRows-1:0] c3sram_wl_o
);

typedef enum logic [2:0] { 
    S_IDLE = 0, 
    S_WRITING = 1, 
    S_READING = 2 
} wr_ctrl_state_t;

wr_ctrl_state_t state_q;
wr_ctrl_state_t state_d;

logic [1:0] pos_ctr;
logic [$clog2(numRows)-1:0] addr_i_q;

// FSM
always_ff @(posedge clk or negedge nrst) begin
    if (!nrst) begin
        state_q <= S_IDLE;
    end else begin
        state_q <= state_d;
    end
end
always_comb begin
    case (state_q)
        S_IDLE: begin
            case({write_i,read_i})
                default: state_d = S_IDLE;
                2'b10:   state_d = S_WRITING;
                2'b01:   state_d = S_READING;
            endcase
        end
        S_WRITING, S_READING: begin 
            if (pos_ctr == 0) begin
                state_d = S_IDLE;
            end else begin
                state_d = state_q;
            end
        end 
        default: state_d = state_q;
    endcase
end

// Data registering when writing
always_ff @( posedge clk ) begin : wrDataReg
    if (!nrst) begin
        wr_data_q <= 0;
        addr_i_q <= 0;
    end else begin
        if (state_q == S_IDLE) begin
            if (state_d == S_WRITING) begin
                wr_data_q <= wr_data_i;
                addr_i_q <= addr_i;
            end
            if (state_d == S_READING) begin
                addr_i_q <= addr_i;
            end
        end 

    end
end

// Position Counter
always_ff @(posedge clk or negedge nrst) begin : positionCounter
    if (!nrst) begin
        pos_ctr <= 3;
    end else begin
        case (state_q)
            S_IDLE: pos_ctr <= 3;
            S_WRITING, S_READING: pos_ctr <= pos_ctr - 1;
            default: pos_ctr <= pos_ctr;
        endcase
    end
end

localparam w2bWaveWr  = 4'b1111;
localparam nprechargeWaveWr = 4'b1111;
localparam targetWlWaveWr = 4'b0110;

localparam saenWaveRd = 4'b0010;
// localparam cselWaveRd = 4'b1010;
localparam cselWaveRd = 4'b0000;
localparam nprechargeWaveRd = 4'b1110;
localparam targetWlWaveRd = 4'b0110;

// C3SRAM Signals
always_comb  begin
    case (state_q)
        default: begin
            c3sram_csel_o = 0;
            c3sram_saen_o = 0;
            c3sram_w2b_o = 0;
            c3sram_wl_o = 0;
            c3sram_nprecharge_o = 0;
        end
        S_READING: begin
            c3sram_csel_o = cselWaveRd[pos_ctr];
            c3sram_saen_o = saenWaveRd[pos_ctr];
            c3sram_w2b_o = 0;
            c3sram_wl_o = 0;
            c3sram_wl_o[addr_i_q] = targetWlWaveRd[pos_ctr];
            c3sram_nprecharge_o = nprechargeWaveRd[pos_ctr];
        end
        S_WRITING: begin
            c3sram_csel_o = 0;
            c3sram_saen_o = 0;
            c3sram_w2b_o = w2bWaveWr[pos_ctr];
            c3sram_wl_o = 0;
            c3sram_wl_o[addr_i_q] = targetWlWaveWr[pos_ctr];
            c3sram_nprecharge_o = nprechargeWaveWr[pos_ctr];
        end
    endcase
end

// Done
always_comb ready = (state_q == S_IDLE) ? 1 : 0;
always_comb begin 
    case (state_q)
        S_READING:
            done = (pos_ctr == 1);
        default: begin
            done = (pos_ctr == 0);
        end
    endcase
end

endmodule