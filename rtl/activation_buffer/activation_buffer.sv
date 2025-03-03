/*
Activations only need a fifo
*/

module activation_buffer #(
    parameter dataSize = 8,      
    parameter depth = 1024,
    parameter addrWidth = 32,    
    parameter interfaceWidth = 32,
    localparam totalSize = depth*dataSize
) (
    input logic clk,
    input logic nrst,
    
    // Write Interface
    input        [interfaceWidth-1:0]   wr_data_i,
    output logic [interfaceWidth-1:0]   rd_data_o,
    input logic ctrl_wr_en,
    input logic ctrl_rd_en,

    // For Debugging
    output logic [addrWidth-1:0]        ofmap_head_snoop,
    output logic [addrWidth-1:0]        ifmap_head_snoop
);

//-----------------------------------
// Signals
//-----------------------------------

// RAM
logic [addrWidth-1:0] ram_wr_addr;
logic [interfaceWidth-1:0] ram_wr_data;
logic [interfaceWidth-1:0] ram_rd_data;
logic [addrWidth-1:0] ram_rd_addr;

logic [addrWidth-1:0] head;
logic [addrWidth-1:0] tail;

//-----------------------------------
// Modules
//-----------------------------------
ram_1w1r #(
    .addrWidth      (addrWidth),
    .dataSize       (dataSize),
    .interfaceWidth (interfaceWidth),
    .depth          (depth)
) u_ram (
    .clk            (clk),
    .nrst           (nrst),
    .wr_en_i        (ctrl_wr_en),
    .wr_addr_i      (head),
    .wr_data_i      (wr_data_i),
    .rd_en_i        (ctrl_rd_en),
    .rd_data_o      (rd_data_o),
    .rd_addr_i      (tail)
);

//-----------------------------------
// Control Logic
//-----------------------------------

always_ff @( posedge clk or negedge nrst ) begin : headsControl
    if (!nrst) begin
        head <= 0;
        tail <= 0;
    end else begin
        if (ctrl_wr_en) begin
            head <= head + 1;
        end
        if (ctrl_rd_en) begin
            tail <= tail + 1;
        end
    end
end

always_comb begin : headsAssigns
    ofmap_head_snoop = head;
    ifmap_head_snoop = tail;
end

endmodule