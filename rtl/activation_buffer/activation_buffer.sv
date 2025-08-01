/*

SRAM Wrapper

Prioritizes reads over writes

*/

`timescale 1ns/1ps

module activation_buffer #(
    parameter addrWidth = 18,
    parameter dataSize = 8,

    parameter interfaceWidth1 = 32,
    parameter interfaceWidth2 = 256,

    localparam numBanks = 32
) (
    input logic clk, nrst,

    input logic wr_en_1_i,
    input logic [addrWidth-1:0] wr_addr_1_i,
    input logic [interfaceWidth1-1:0] wr_data_1_i,
    input logic rd_en_1_i,
    input logic [addrWidth-1:0] rd_addr_1_i,
    output logic [interfaceWidth1-1:0] rd_data_1_o,

    input logic wr_en_2_i,
    input logic [addrWidth-1:0] wr_addr_2_i,
    input logic [interfaceWidth2-1:0] wr_data_2_i,
    input logic rd_en_2_i,
    input logic [addrWidth-1:0] rd_addr_2_i,
    output logic [interfaceWidth2-1:0] rd_data_2_o,

    output logic wr_ready_o
);

logic [17:0] sram_addr;
logic [interfaceWidth2-1:0] sram_wr_data;
logic [interfaceWidth2-1:0] sram_rd_data;
logic [interfaceWidth2-1:0] sram_rd_data_q;
logic rd_en_q;
logic [interfaceWidth2-1:0] sram_rd_data_latched;
logic sram_wr_en;
logic [numBanks-1:0] bank_mask; // Mask for which banks to write to
logic rd_select;

// Module from other folder, linked
sram_32bank_8b #(
    .wordSize(8),
    .interfaceSize(interfaceWidth2), // 256 bits for 32 banks of 8 bits e  ach
    .numBanks(numBanks), // 8 banks of 32kB = 256kB
    .addrWidth(18) // 256kB total, 18-bit address width 
) u_sram_ip (
    .clk(clk),
    .nrst(nrst),

    .wr_data_i(sram_wr_data),
    .bank_mask_i(bank_mask),
    .addr_i(sram_addr),
    .rd_data_o(sram_rd_data),

    .wr_en_i(sram_wr_en)
);

always_ff @( posedge clk or negedge nrst ) begin : readDataRegister
    if (!nrst) begin
        sram_rd_data_q <= '0;
        rd_en_q <= 1'b0;
    end else begin
        rd_en_q <= rd_en_1_i | rd_en_2_i; // Capture read enable state
        if (rd_en_q) begin
            sram_rd_data_q <= sram_rd_data; // Latch read data on read request
        end
    end
end

assign sram_rd_data_latched = rd_en_q ? sram_rd_data : sram_rd_data_q;


logic [interfaceWidth1-1:0] wr_data_1_i_flipped;

always_comb begin : wrData1Flip // The endianness of the compiler is wrong
    wr_data_1_i_flipped = '0;
    for (int i = 0; i < interfaceWidth1; i += 8) begin
        wr_data_1_i_flipped[i +: 8] = wr_data_1_i[(interfaceWidth1 - 8 - i) +: 8];
    end
end

always_comb begin : readPrioritization
    // Default values
    wr_ready_o = 1'b0;
    sram_wr_en = 1'b0;
    sram_addr = '0; // Default read address
    bank_mask = 32'hFFFF_FFFF; // Default bank mask
    sram_wr_data = '0;
    if (rd_en_2_i | rd_en_1_i) begin
        wr_ready_o = 0; 
        sram_wr_en = 1'b0;         
        sram_addr = rd_en_1_i ? rd_addr_1_i : rd_addr_2_i;
        bank_mask = rd_en_1_i ? 32'h0000_000F : 32'hFFFF_FFFF;
    end else if (wr_en_1_i | wr_en_2_i) begin
        wr_ready_o = 1'b1; // Use to acknowledge writes
        sram_wr_en = 1'b1;
        sram_addr = wr_en_1_i ? wr_addr_1_i : wr_addr_2_i;
        sram_wr_data = wr_en_1_i ? wr_data_1_i_flipped : wr_data_2_i;
        bank_mask = wr_en_1_i ? 32'h0000_000F : 32'hFFFF_FFFF;
    end
    rd_data_1_o = sram_rd_data_latched[256-1 -: interfaceWidth1];
    rd_data_2_o = sram_rd_data_latched[interfaceWidth2-1:0]; 
end

endmodule