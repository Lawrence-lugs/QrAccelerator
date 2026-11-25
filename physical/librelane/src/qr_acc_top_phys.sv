// Digital-only physical top for the LibreLane flow.
//
// The analog buses are intentionally not top pins:
//   - from_analog is tied to zero
//   - to_analog is left open and will be trimmed
// The later SoC integration must restore both buses; see README.md.

module qr_acc_top_phys (
    input  logic clk,
    input  logic nrst,

    input  logic [31:0] bus_req_data,
    input  logic [31:0] bus_req_addr,
    input  logic        bus_req_wen,
    input  logic        bus_req_valid,

    output logic        bus_resp_ready,
    output logic [31:0] bus_resp_data,
    output logic        bus_resp_rd_valid,

    output logic [7:0]  bank_select
);

    import qracc_pkg::*;

    localparam int NP = 8;

    bus_req_t req;
    bus_resp_t resp;

    assign req.data_in = bus_req_data;
    assign req.addr    = bus_req_addr;
    assign req.wen     = bus_req_wen;
    assign req.valid   = bus_req_valid;

    assign bus_resp_ready    = resp.ready;
    assign bus_resp_data     = resp.data_out;
    assign bus_resp_rd_valid = resp.rd_data_valid;

    to_analog_t to_analog [NP-1:0];
    from_analog_t from_analog [NP-1:0];

    always_comb begin
        for (int p = 0; p < NP; p++) begin
            from_analog[p] = '0;
        end
    end

    qr_acc_top #(
        .globalBufferDepth(262144)
    ) u_top (
        .clk(clk),
        .nrst(nrst),
        .bus_req_i(req),
        .bus_resp_o(resp),
        .to_analog(to_analog),
        .from_analog(from_analog),
        .bank_select(bank_select)
    );

endmodule
