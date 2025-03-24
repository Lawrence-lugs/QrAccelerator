// Standin for some other memory type
// Ultra generic single-cycle memory
// Responds in 1 cycle

module ram_1w1r #(
    parameter addrWidth = 16,
    parameter dataSize = 8,
    parameter interfaceWidth = 32,
    parameter depth = 1024 // 1024 datas
) (
    input logic clk, nrst,

    input logic [addrWidth-1:0] wr_addr_i,
    input logic wr_en_i,
    input logic [interfaceWidth-1:0] wr_data_i,
    
    input logic [addrWidth-1:0] rd_addr_i,
    input logic rd_en_i,
    output logic [interfaceWidth-1:0] rd_data_o
);

// Signals
logic [dataSize-1:0] mem [depth-1:0];

// Modules
always_ff @(posedge clk, negedge nrst) begin
    if (!nrst) begin
        for (int i = 0; i < depth; i++) begin
            mem[i] <= 0;
        end
        rd_data_o <= 0;
    end else begin
        if (wr_en_i) begin
            for (int i = 0; i < interfaceWidth/dataSize; i++) begin
                // Little endian
                mem[wr_addr_i + i] <= wr_data_i[i*dataSize +: dataSize];
            end
        end 
        if (rd_en_i) begin
            for (int i = 0; i < interfaceWidth/dataSize; i++) begin
                // Little endian read
                rd_data_o[i*dataSize +: dataSize] <= mem[rd_addr_i + (interfaceWidth/dataSize-1-i)];
            end
        end else begin
            rd_data_o <= 0;
        end
    end
end
    
endmodule