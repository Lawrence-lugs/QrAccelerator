// Write data_queue with parallel write and serial read

module piso_write_queue #(
    parameter numParallelIn = 8,
    parameter writeInterfaceWidth = 32,
    parameter queueDepth = 8,
    parameter maxBits = 8,
    parameter writeAddrWidth = 16
) (
    input clk, nrst,
    input logic [numParallelIn-1:0][writeInterfaceWidth-1:0] data_in,
    input logic [numParallelIn-1:0][writeAddrWidth-1:0] addr_in,
    input logic [numParallelIn-1:0] valid_in,
    input logic ready_out,
    output logic [writeAddrWidth-1:0] addr_out,
    output logic [writeInterfaceWidth-1:0] data_out,
    output logic valid_out
);

    // Internal storage
    logic [queueDepth-1:0][writeInterfaceWidth-1:0] data_queue;
    logic [queueDepth-1:0][writeAddrWidth-1:0] addr_queue;
    logic [maxBits-1:0] write_ptr, read_ptr;
    logic [maxBits-1:0] count;
    logic queue_empty, queue_full;
    logic [maxBits-1:0] num_valids_this_cycle;

    // Queue status
    assign queue_empty = (count == 0);
    assign queue_full = (count == queueDepth);
    assign valid_out = !queue_empty;

    // Data output
    assign data_out = data_queue[read_ptr];
    assign addr_out = addr_queue[read_ptr];

    // Valid counting
    always_comb begin
        num_valids_this_cycle = 0;
        for (int i = 0; i < numParallelIn; i++) begin
            if (valid_in[i]) begin
                num_valids_this_cycle++;
            end
        end
    end

    // Queue management
    always_ff @(posedge clk or negedge nrst) begin
        if (!nrst) begin
            write_ptr <= '0;
            read_ptr <= '0;
            count <= '0;
            data_queue <= '0;
            addr_queue <= '0;
        end else begin
            // Handle parallel write
            if (|valid_in && !queue_full) begin
                for (int i = 0 ; i < numParallelIn ; i++) begin
                    if (valid_in[i]) begin
                        data_queue[write_ptr] <= data_in[i];
                        addr_queue[write_ptr] <= addr_in[i];
                    end
                end
                write_ptr <= (write_ptr + num_valids_this_cycle) % queueDepth;
                count <= count + num_valids_this_cycle;
            end

            // Handle serial read
            if (!queue_empty) begin
                read_ptr <= (read_ptr + 1) % queueDepth;
                count <= count - 1;
            end
        end
    end

endmodule