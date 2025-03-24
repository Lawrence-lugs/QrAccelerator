// Standin for some other memory type
// Ultra generic single-cycle memory
// Responds in 1 cycle

module ram_2w1r #(
    parameter addrWidth1 = 32,
    parameter addrWidth2 = 32,
    parameter dataSize = 8,
    parameter interfaceWidth1 = 32,
    parameter interfaceWidth2 = 256,
    parameter depth = 1024
) (
    input logic clk, nrst,

    input logic wr_en_1_i,
    input logic [addrWidth-1:0] wr_addr_1_i,
    input logic [interfaceWidth1-1:0] wr_data_1_i,

    input logic wr_en_2_i,
    input logic [addrWidth-1:0] wr_addr_2_i,
    input logic [interfaceWidth2-1:0] wr_data_2_i,

    input logic rd_en_i,
    input logic [addrWidth-1:0] rd_addr_i,

    output logic [interfaceWidth-1:0] data_o
);

logic [dataSize-1:0] mem [depth];

always_ff @(posedge clk, negedge nrst) begin
    if (!nrst) begin
        for (int i = 0; i < depth; i++) begin
            mem[i] <= 0;
        end
        data_o <= 0;
    end else begin
        if (wr_en_1_i) begin
            for (int i = 0; i < interfaceWidth/dataSize; i++) begin
                mem[wr_addr_1_i + i] <= wr_data_1_i[i*dataSize +: dataSize];
            end
        end 
        if (wr_en_2_i) begin
            for (int i = 0; i < interfaceWidth/dataSize; i++) begin
                mem[wr_addr_2_i + i] <= wr_data_2_i[i*dataSize +: dataSize];
            end
        end
        if (rd_en_i) begin
            for (int i = 0; i < interfaceWidth/dataSize; i++) begin
                // Little endian read
                data_o[i*dataSize +: dataSize] <= mem[rd_addr_i + (interfaceWidth/dataSize-1-i)];
            end
        end else begin
            data_o <= 0;
        end
    end
end
    
endmodule