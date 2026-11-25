// Banked 2W2R ACTMEM built from IHP SG13G2 2-port SRAM macros.
//
// The IHP library has no 4-port SRAM.  Each RM_IHPSG13_2P_256x32 macro has two
// independent read/write ports, so this wrapper uses one port for writes and one
// for reads and banks eight 32-bit macros to form a 256-bit row.  External and
// internal accesses are mutually exclusive in qracc_controller (S_LOADACTS /
// S_READACTS versus S_COMPUTE_*), so a priority mux is sufficient.
//
// Layout: eight banks x 32 bits = 256 bits per row.  Byte addresses are split
// into word index [..:2], bank [2:0] and macro row [..:3].  A 256-bit access may
// start at any 4-byte boundary; the eight words rotate across banks and, at most,
// two macro rows.  Byte order matches rtl/memory/ram_2w2r.sv exactly, including
// its byte-reversed internal-port read.
//
// Constraints: dataSize == 8, interfaceWidth1 == 32, interfaceWidth2 == 256,
// depth is a multiple of 32, and both port addresses are 4-byte aligned.  The
// controller already uses 4-byte-aligned activation-buffer addresses.

module actmem_2w2r_ihp #(
    parameter addrWidth = 32,
    parameter dataSize = 8,
    parameter interfaceWidth1 = 32,
    parameter interfaceWidth2 = 256,
    parameter depth = 256,
    parameter int MACRO_ROWS = 256
) (
    input  logic clk,
    input  logic nrst,

    input  logic wr_en_1_i,
    input  logic [addrWidth-1:0] wr_addr_1_i,
    input  logic [interfaceWidth1-1:0] wr_data_1_i,
    input  logic rd_en_1_i,
    input  logic [addrWidth-1:0] rd_addr_1_i,
    output logic [interfaceWidth1-1:0] rd_data_1_o,

    input  logic wr_en_2_i,
    input  logic [addrWidth-1:0] wr_addr_2_i,
    input  logic [interfaceWidth2-1:0] wr_data_2_i,
    input  logic rd_en_2_i,
    input  logic [addrWidth-1:0] rd_addr_2_i,
    output logic [interfaceWidth2-1:0] rd_data_2_o
);

    localparam int WORD_BYTES = 4;
    localparam int NUM_BANKS = interfaceWidth2 / 32;
    localparam int BANK_W = (NUM_BANKS > 1) ? $clog2(NUM_BANKS) : 1;
    localparam int BYTE_ADDR_W = $clog2(depth);
    localparam int WORD_ADDR_W = $clog2(depth / WORD_BYTES);
    localparam int ROWS = depth / 32;
    localparam int MACRO_AW = $clog2(MACRO_ROWS);
    localparam int ROW_BANKS = (ROWS + MACRO_ROWS - 1) / MACRO_ROWS;
    localparam int ROW_BANK_W = (ROW_BANKS > 1) ? $clog2(ROW_BANKS) : 1;

    function automatic [31:0] bswap32(input [31:0] x);
        bswap32 = {x[7:0], x[15:8], x[23:16], x[31:24]};
    endfunction

    // Word index, bank and macro row for a byte address.
    function automatic [WORD_ADDR_W-1:0] word_of(input [addrWidth-1:0] a);
        word_of = a[BYTE_ADDR_W-1:2];
    endfunction

    function automatic [MACRO_AW-1:0] macro_row_of(input [WORD_ADDR_W-1:0] w);
        macro_row_of = (w >> 3) & (MACRO_ROWS - 1);
    endfunction

    function automatic [ROW_BANK_W-1:0] row_bank_of(input [WORD_ADDR_W-1:0] w);
        row_bank_of = (w >> 3) >> MACRO_AW;
    endfunction

    function automatic [31:0] word_select(input [interfaceWidth2-1:0] data,
                                          input [BANK_W-1:0] idx);
        word_select = data[32*idx +: 32];
    endfunction

    logic [WORD_ADDR_W-1:0] w1_wr, w1_rd, w2_wr, w2_rd;
    assign w1_wr = word_of(wr_addr_1_i);
    assign w1_rd = word_of(rd_addr_1_i);
    assign w2_wr = word_of(wr_addr_2_i);
    assign w2_rd = word_of(rd_addr_2_i);

    logic [BANK_W-1:0] bank1_wr, bank1_rd;
    logic [ROW_BANK_W-1:0] rowbank1_wr, rowbank1_rd;
    logic [MACRO_AW-1:0] macro_row1_wr, macro_row1_rd;

    assign bank1_wr = w1_wr[BANK_W-1:0];
    assign bank1_rd = w1_rd[BANK_W-1:0];
    assign rowbank1_wr = row_bank_of(w1_wr);
    assign rowbank1_rd = row_bank_of(w1_rd);
    assign macro_row1_wr = macro_row_of(w1_wr);
    assign macro_row1_rd = macro_row_of(w1_rd);

    // Macro outputs, flattened so the read assembly can index them.
    logic [NUM_BANKS*ROW_BANKS-1:0][31:0] dout_flat;

    generate
        for (genvar b = 0; b < NUM_BANKS; b++) begin : g_bank
            localparam logic [BANK_W-1:0] B = b;
            localparam logic [BANK_W-1:0] BMASK = NUM_BANKS - 1;

            // Port 2 words rotate by the starting word offset.
            wire [BANK_W-1:0] w_b_wr = (B - w2_wr[BANK_W-1:0]) & BMASK;
            wire [BANK_W-1:0] w_b_rd = (B - w2_rd[BANK_W-1:0]) & BMASK;

            wire [WORD_ADDR_W-1:0] mw_wr = w2_wr + w_b_wr;
            wire [WORD_ADDR_W-1:0] mw_rd = w2_rd + w_b_rd;

            wire [MACRO_AW-1:0] macro_row2_wr = macro_row_of(mw_wr);
            wire [MACRO_AW-1:0] macro_row2_rd = macro_row_of(mw_rd);
            wire [ROW_BANK_W-1:0] rowbank2_wr = row_bank_of(mw_wr);
            wire [ROW_BANK_W-1:0] rowbank2_rd = row_bank_of(mw_rd);

            wire [31:0] data2_wr = word_select(wr_data_2_i, w_b_wr);

            wire wr_sel_b = wr_en_2_i || (wr_en_1_i && (bank1_wr == B));
            wire rd_sel_b = rd_en_2_i || (rd_en_1_i && (bank1_rd == B));

            wire [MACRO_AW-1:0] wr_addr_b = wr_en_2_i ? macro_row2_wr : macro_row1_wr;
            wire [MACRO_AW-1:0] rd_addr_b = rd_en_2_i ? macro_row2_rd : macro_row1_rd;
            wire [ROW_BANK_W-1:0] wr_rb_b = wr_en_2_i ? rowbank2_wr : rowbank1_wr;
            wire [ROW_BANK_W-1:0] rd_rb_b = rd_en_2_i ? rowbank2_rd : rowbank1_rd;
            wire [31:0] wr_data_b = wr_en_2_i ? data2_wr : bswap32(wr_data_1_i);

            for (genvar rb = 0; rb < ROW_BANKS; rb++) begin : g_rb
                wire [31:0] unused_a_dout;

                if (MACRO_ROWS == 1024) begin : g_macro1024
                    RM_IHPSG13_2P_1024x32_c2_bm_bist u_macro (
                        .A_CLK(clk),
                        .A_MEN(wr_sel_b && (wr_rb_b == rb)),
                        .A_WEN(1'b1),
                        .A_REN(1'b0),
                        .A_ADDR(wr_addr_b),
                        .A_DIN(wr_data_b),
                        .A_DLY(1'b1),
                        .A_DOUT(unused_a_dout),
                        .A_BM(32'hFFFFFFFF),
                        .A_BIST_CLK(clk),
                        .A_BIST_EN(1'b0),
                        .A_BIST_MEN(1'b0),
                        .A_BIST_WEN(1'b0),
                        .A_BIST_REN(1'b0),
                        .A_BIST_ADDR(10'b0),
                        .A_BIST_DIN(32'b0),
                        .A_BIST_BM(32'hFFFFFFFF),

                        .B_CLK(clk),
                        .B_MEN(rd_sel_b && (rd_rb_b == rb)),
                        .B_WEN(1'b0),
                        .B_REN(1'b1),
                        .B_ADDR(rd_addr_b),
                        .B_DIN(32'b0),
                        .B_DLY(1'b1),
                        .B_DOUT(dout_flat[b*ROW_BANKS + rb]),
                        .B_BM(32'hFFFFFFFF),
                        .B_BIST_CLK(clk),
                        .B_BIST_EN(1'b0),
                        .B_BIST_MEN(1'b0),
                        .B_BIST_WEN(1'b0),
                        .B_BIST_REN(1'b0),
                        .B_BIST_ADDR(10'b0),
                        .B_BIST_DIN(32'b0),
                        .B_BIST_BM(32'hFFFFFFFF)
                    );
                end else begin : g_macro256
                    RM_IHPSG13_2P_256x32_c2_bm_bist u_macro (
                        .A_CLK(clk),
                        .A_MEN(wr_sel_b && (wr_rb_b == rb)),
                        .A_WEN(1'b1),
                        .A_REN(1'b0),
                        .A_ADDR(wr_addr_b),
                        .A_DIN(wr_data_b),
                        .A_DLY(1'b1),
                        .A_DOUT(unused_a_dout),
                        .A_BM(32'hFFFFFFFF),
                        .A_BIST_CLK(clk),
                        .A_BIST_EN(1'b0),
                        .A_BIST_MEN(1'b0),
                        .A_BIST_WEN(1'b0),
                        .A_BIST_REN(1'b0),
                        .A_BIST_ADDR(8'b0),
                        .A_BIST_DIN(32'b0),
                        .A_BIST_BM(32'hFFFFFFFF),

                        .B_CLK(clk),
                        .B_MEN(rd_sel_b && (rd_rb_b == rb)),
                        .B_WEN(1'b0),
                        .B_REN(1'b1),
                        .B_ADDR(rd_addr_b),
                        .B_DIN(32'b0),
                        .B_DLY(1'b1),
                        .B_DOUT(dout_flat[b*ROW_BANKS + rb]),
                        .B_BM(32'hFFFFFFFF),
                        .B_BIST_CLK(clk),
                        .B_BIST_EN(1'b0),
                        .B_BIST_MEN(1'b0),
                        .B_BIST_WEN(1'b0),
                        .B_BIST_REN(1'b0),
                        .B_BIST_ADDR(8'b0),
                        .B_BIST_DIN(32'b0),
                        .B_BIST_BM(32'hFFFFFFFF)
                    );
                end
            end
        end
    endgenerate

    logic [31:0] rd1_comb;
    logic [interfaceWidth2-1:0] rd2_comb;

    always_comb begin
        int rb;
        rb = row_bank_of(w1_rd);
        rd1_comb = bswap32(dout_flat[bank1_rd*ROW_BANKS + rb]);
    end

    // Internal-port reads return the stored 32-byte block in reverse byte order,
    // matching ram_2w2r.sv.
    always_comb begin
        rd2_comb = '0;
        for (int w = 0; w < NUM_BANKS; w++) begin
            int mw;
            int b;
            int rb;
            mw = w2_rd + (NUM_BANKS - 1 - w);
            b = mw & (NUM_BANKS - 1);
            rb = (mw >> 3) >> MACRO_AW;
            rd2_comb[32*w +: 32] = bswap32(dout_flat[b*ROW_BANKS + rb]);
        end
    end

    logic rd_seen_1, rd_seen_2;

    always_ff @(posedge clk or negedge nrst) begin
        if (!nrst) begin
            rd_seen_1 <= 1'b0;
            rd_seen_2 <= 1'b0;
        end else begin
            if (rd_en_1_i) rd_seen_1 <= 1'b1;
            if (rd_en_2_i) rd_seen_2 <= 1'b1;
        end
    end

    assign rd_data_1_o = (nrst && rd_seen_1) ? rd1_comb : '0;

    always_comb begin
        if (!nrst || !rd_seen_2) rd_data_2_o = '0;
        else rd_data_2_o = rd2_comb;
    end

endmodule
