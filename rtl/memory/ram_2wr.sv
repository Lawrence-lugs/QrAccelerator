// Dual port RAM
// Single cycle response

module ram_2wr #(
    parameter addrWidth = 32,
    parameter dataSize = 8,

    parameter interfaceWidth1 = 32,
    parameter interfaceWidth2 = 256,
    
    parameter depth = 1024
) (
    input logic clk, nrst,

    input logic wr_en_1_i,
    input logic [addrWidth-1:0] addr_1_i,
    input logic [interfaceWidth1-1:0] wr_data_1_i,
    output logic [interfaceWidth1-1:0] rd_data_1_o,

    input logic wr_en_2_i,
    input logic [addrWidth-1:0] addr_2_i,
    input logic [interfaceWidth2-1:0] wr_data_2_i,
    output logic [interfaceWidth2-1:0] rd_data_2_o
);

logic [dataSize-1:0] mem [depth];

always_ff @(posedge clk, negedge nrst) begin
    if (!nrst) begin
        for (int i = 0; i < depth; i++) begin
            mem[i] <= 0;
        end
        rd_data_1_o <= 0;
        rd_data_2_o <= 0;
    end else begin
        if (wr_en_1_i) begin
            for (int i = 0; i < interfaceWidth1/dataSize; i++) begin
                mem[addr_1_i + i] <= wr_data_1_i[i*dataSize +: dataSize];
            end
        end else begin
            for (int i = 0; i < interfaceWidth1/dataSize; i++) begin
                rd_data_1_o[i*dataSize +: dataSize] <= mem[addr_1_i + (interfaceWidth1/dataSize-1-i)];
            end
        end
        if (wr_en_2_i) begin
            for (int i = 0; i < interfaceWidth2/dataSize; i++) begin
                mem[addr_2_i + i] <= wr_data_2_i[i*dataSize +: dataSize];
            end
        end else begin
            for (int i = 0; i < interfaceWidth2/dataSize; i++) begin
                rd_data_2_o[i*dataSize +: dataSize] <= mem[addr_2_i + (interfaceWidth2/dataSize-1-i)];
            end
        end
    end
end
    
endmodule