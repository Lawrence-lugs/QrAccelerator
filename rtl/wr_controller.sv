
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


`timescale 1ns/1ps

module wr_controller #(
    parameter int numRows = 8,
    parameter int numCols = 8
) (
    input clk,
    input nrst,
    
    // we don't passively read in the interest of energy
    input write_i,
    input read_i,
    input [$clog2(numRows)-1:0] addr_i,

    output logic done, //asserted for just 1 CC
    output logic ready,

    // writes and reads
    output logic c3sram_csel_o,
    output logic c3sram_saen_o,
    output logic c3sram_w2b_o,
    output logic c3sram_nprecharge_o,
    output logic [numRows-1:0] c3sram_wl_o
);

typedef enum { S_IDLE, S_WRITING, S_READING } wr_ctrl_state_t;

wr_ctrl_state_t state_q;
wr_ctrl_state_t state_d;

logic [2:0] pos_ctr;

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

// Position Counter
always_ff @(posedge clk or negedge nrst) begin : positionCounter
    if (!nrst) begin
        pos_ctr <= 3;
    end else begin
        case (state_q)
            S_IDLE: pos_ctr <= 3;
            S_WRITING, S_READING: pos_ctr <= pos_ctr - 1;
        endcase
    end
end

localparam w2bWaveWr  = 4'b1111;
localparam nprechargeWaveWr = 4'b1111;
localparam targetWlWaveWr = 4'b0110;

localparam saenWaveRd = 4'b0010;
localparam cselWaveRd = 4'b1010;
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
            c3sram_wl_o[addr_i] = targetWlWaveRd[pos_ctr];
            c3sram_nprecharge_o = nprechargeWaveRd[pos_ctr];
        end
        S_WRITING: begin
            c3sram_csel_o = 0;
            c3sram_saen_o = 0;
            c3sram_w2b_o = w2bWaveWr[pos_ctr];
            c3sram_wl_o = 0;
            c3sram_wl_o[addr_i] = targetWlWaveWr[pos_ctr];
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