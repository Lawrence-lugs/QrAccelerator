module wsacc_pe_cluster #(
    parameter numPes = 32,
    parameter int windowElements = 9,
    parameter int outputWidth = 16,
    parameter int weightInterfaceWidth = 32,
    localparam dataWidth = 8 // We design the cluster for 8-bit data
) (
    input clk, nrst,

    input [numPes-1:0][windowElements-1:0][dataWidth-1:0] data_i,
    input data_i_valid,
    output logic data_i_ready,
    input [weightInterfaceWidth-1:0] weight_itf_i,
    input weight_itf_i_valid,
    output logic weight_writing_done,

    output logic [numPes-1:0][outputWidth-1:0] data_o,
    output logic data_o_valid,
    input data_o_ready
);

    // Parameters
    localparam numPesInWriteSet = weightInterfaceWidth/dataWidth;
    localparam numWriteSets = numPes % numPesInWriteSet ? (numPes / numPesInWriteSet) + 1 : (numPes / numPesInWriteSet);

    // Internal signals
    logic [numPes-1:0][outputWidth-1:0] data_o_d;
    logic [numPes-1:0][dataWidth-1:0] weight_i;
    logic [numPes-1:0] weight_wr_en;
    logic [3:0] weight_addr;
    logic [7:0] write_set;
    logic [7:0] write_set_offset;
    logic [7:0] pes_skipped;

    // Weight interface to weight_i reconciliation
    always_comb begin : weightItfDpth
        weight_wr_en = 0;
        pes_skipped = (numPesInWriteSet * write_set);
        weight_i = 0;
        // write_set_offset = write_set * (pes_skipped * dataWidth);
        for (int i = 0; i < numPesInWriteSet; i++) begin
            // Write in uniform table format
            weight_i[i + pes_skipped] = weight_itf_i[(i * dataWidth) +: dataWidth];
            weight_wr_en[i + pes_skipped] = weight_itf_i_valid;
        end
    end
    always_ff @( posedge clk or negedge nrst ) begin : weightItfCtrl
        if (!nrst) begin
            write_set <= 0;
            weight_addr <= '0;
            weight_writing_done <= 1'b0;
            $display("PE,\twrite_set,\tpes_skipped,\twrite_set_offset,\tData");
        end else begin
            if (weight_itf_i_valid) begin
                if(write_set == numWriteSets-1) begin
                    write_set <= 0;
                    if (weight_addr < windowElements - 1) begin
                        weight_addr <= weight_addr + 1;
                    end else begin
                        weight_writing_done <= 1'b1;
                        weight_addr <= 0;
                    end
                end else begin
                    weight_writing_done <= 1'b0;
                    write_set <= write_set + 1;
                end
            end
        end
    end

    // Ready when output isn't stalling
    assign data_i_ready = data_o_valid ? data_o_ready : 1'b1;

    // Register output data
    always_ff @(posedge clk or negedge nrst) begin
        if (!nrst) begin
            data_o_valid <= 1'b0;
            data_o <= '0;
        end else begin
            if (data_i_valid && data_i_ready) begin
                data_o_valid <= 1'b1;
                data_o <= data_o_d;
            end else begin
                data_o_valid <= 0;
            end
            // The only case where we can clear data_o_valid is when
            if (data_o_valid && data_o_ready && ~data_i_valid) data_o_valid <= 1'b0;
        end
    end

    // PE array itself
    genvar pe_idx;
    generate
        for (pe_idx = 0; pe_idx < numPes; pe_idx++) begin : pe_array
            wsacc_pe #(
                .dataWidth(dataWidth),
                .outputWidth(outputWidth),
                .windowElements(windowElements)
            ) pe_inst (
                .clk(clk),
                .nrst(nrst),
                .weight_wr_en(weight_wr_en[pe_idx]),
                .weight_addr(weight_addr),
                .weight_i(weight_i[pe_idx]),
                .data_i(data_i[pe_idx]),
                .data_o(data_o_d[pe_idx])
            );
        end
    endgenerate

endmodule