`timescale 1ns/1ps

module regfile #(
    parameter numReg = 64,
    parameter regWidth = 32,
    parameter numWrite = 1,
    parameter numRead = 1,

    localparam addrWidth = $clog2(numReg)
) (
    input clk, nrst,

    input [numWrite-1:0][regWidth-1:0] wr_data_i,
    input [numWrite-1:0][addrWidth-1:0] wr_addr_i,
    input [numWrite-1:0] wr_en_i,

    input [numRead-1:0][addrWidth-1:0] rd_addr_i, 

    output logic [numRead-1:0][regWidth-1:0] rd_data_o
);

    // Signals
    logic [regWidth-1:0] registers [numReg];

    // Modules
    always_ff @(posedge clk, negedge nrst) begin
        if (!nrst) begin
            for (int i = 0; i < numReg; i++) begin
                registers[i] <= 0;
            end
        end else begin
            for (int i = 0; i < numWrite; i++) begin
                if (wr_en_i[i]) begin
                    registers[wr_addr_i[i]] <= wr_data_i[i];
                end
            end
        end
    end

    always_comb begin
        for (int i = 0; i < numRead; i++) begin
            rd_data_o[i] = registers[rd_addr_i[i]];
        end
    end
    
endmodule