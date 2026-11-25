// Physical wrapper for feature_loader.
//
// The RTL exposes a 32-bit write address because the top-level controller
// carries a 32-bit address bus, but the register file has only 288 entries.
// Carrying all 32 bits into the write decoder makes Yosys build a 32-bit
// comparator for every entry and every write lane, which dominates the block.
//
// This wrapper keeps the 32-bit top-level port and drives a 9-bit core.  Writes
// outside the valid 0..numElements-1 range are suppressed, matching the
// original out-of-range behaviour.  The top-level RTL should eventually expose
// a narrow address port (or a wrapper abstraction) so this physical shim can be
// removed.
module feature_loader #(
    parameter inputWidth   = 256,
    parameter addrWidth    = 32,
    parameter elementWidth = 8,
    parameter numElements  = 128
) (
    input  logic clk,
    input  logic nrst,

    input  logic [inputWidth-1:0] data_i,
    input  logic [addrWidth-1:0]  addr_i,
    input  logic                  wr_en,

    output logic [numElements-1:0][elementWidth-1:0] data_o,

    input  logic [15:0] mask_start,
    input  logic [15:0] mask_end
);

    localparam integer CORE_ADDR_WIDTH =
        (numElements > 1) ? $clog2(numElements) : 1;

    logic addr_in_range;
    assign addr_in_range = (addr_i < numElements);

    feature_loader_core #(
        .inputWidth   (inputWidth),
        .addrWidth    (CORE_ADDR_WIDTH),
        .elementWidth (elementWidth),
        .numElements  (numElements)
    ) u_core (
        .clk        (clk),
        .nrst       (nrst),
        .data_i     (data_i),
        .addr_i     (addr_i[CORE_ADDR_WIDTH-1:0]),
        .wr_en      (wr_en && addr_in_range),
        .data_o     (data_o),
        .mask_start (mask_start),
        .mask_end   (mask_end)
    );

endmodule
