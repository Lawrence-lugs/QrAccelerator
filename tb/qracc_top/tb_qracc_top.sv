`timescale 1ns/1ps

import qracc_pkg::*;

`define NUM_ADC_REF_RANGE_SHIFTS 1

module tb_qracc_top #(

/////////////
// PARAMETERS
/////////////

    //  Global Parameter
    parameter CLK_PERIOD = 20,

    //  Parameters: Interface
    parameter dataInterfaceSize = 32,
    parameter ctrlInterfaceSize = 32,

    //  Parameters: CSRs
    parameter csrWidth = 32,
    parameter numCsr = 4,

    //  Parameters: QRAcc
    parameter qrAccInputBits = 4,
    parameter qrAccInputElements = 128,
    parameter qrAccOutputBits = 8,
    parameter qrAccOutputElements = 32,
    parameter qrAccAdcBits = 4,
    parameter qrAccAccumulatorBits = 16, // Internal parameter of seq acc

    //  Parameters: Global Buffer
    parameter globalBufferDepth = 2**21,
    parameter globalBufferExtInterfaceWidth = 32,
    parameter globalBufferIntInterfaceWidth = qrAccInputElements*qrAccInputBits,
    parameter globalBufferAddrWidth = 32,
    parameter globalBufferDataSize = 8,          // Byte-Addressability

    // Parameters: Feature Loader
    parameter aflDimY = 128,
    parameter aflDimX = 6,
    parameter aflAddrWidth = 32

) (
    
);

/////////////
// SIGNALS
/////////////

logic clk;
logic nrst;

qracc_ctrl_interface periph();
qracc_data_interface bus();

to_analog_t to_analog;
from_analog_t from_analog;

qracc_config_t cfg;
logic csr_main_clear;
logic csr_main_start;
logic csr_main_busy;
logic csr_main_inst_write_mode;

/////////////
// MODULES
/////////////

// DUT instantiation
qr_acc_top #(
    .dataInterfaceSize              (dataInterfaceSize),
    .ctrlInterfaceSize              (ctrlInterfaceSize),

    .qrAccInputBits                 (qrAccInputBits),
    .qrAccInputElements             (qrAccInputElements),
    .qrAccOutputBits                (qrAccOutputBits),
    .qrAccOutputElements            (qrAccOutputElements),
    .qrAccAdcBits                   (qrAccAdcBits),
    .qrAccAccumulatorBits           (qrAccAccumulatorBits),

    .globalBufferDepth              (globalBufferDepth),
    .globalBufferExtInterfaceWidth  (globalBufferExtInterfaceWidth),
    .globalBufferIntInterfaceWidth  (globalBufferIntInterfaceWidth),
    .globalBufferAddrWidth          (globalBufferAddrWidth),
    .globalBufferDataSize           (globalBufferDataSize),

    .aflDimY                        (aflDimY),
    .aflDimX                        (aflDimX),
    .aflAddrWidth                   (aflAddrWidth)
) u_qr_acc_top (
    .clk                            (clk),
    .nrst                           (nrst),

    // Control Interface
    .periph_i                       (periph.slave),
    .bus_i                          (bus.slave), 

    // Analog passthrough signals
    .to_analog                      (to_analog),
    .from_analog                    (from_analog),

    // CSR signals for testing for now
    .cfg                            (cfg),
    .csr_main_clear                 (csr_main_clear),
    .csr_main_start                 (csr_main_start),
    .csr_main_busy                  (csr_main_busy),
    .csr_main_inst_write_mode       (csr_main_inst_write_mode)

);

/////////////
// TESTING BOILERPLATE
/////////////

static string files_path = "/home/lquizon/lawrence-workspace/SRAM_test/qrAcc2/qr_acc_2_digital/tb/qracc_top/inputs/";

static string tb_name = "tb_qracc_top";

// Waveform dumping
`ifdef SYNOPSYS
initial begin
    $vcdplusfile({tb_name,".vpd"});
    $vcdpluson();
    $vcdplusmemon();
    $dumpvars(0);
end
`endif
initial begin
    $dumpfile({tb_name,".vcd"});
    $dumpvars(0);
end

// Clock Generation
always #(CLK_PERIOD/2) clk = ~clk;
initial begin
    clk = 0; 
end

// Watchdog
initial begin
    #(100_000_000); // 100 ms
    $display("TEST FAILED - WATCHDOG TIMEOUT");
    $finish;
end

/////////////
// FILE THINGS
/////////////

string files[10] = {
    "flat_output",
    "flat_output_shape",
    "ifmap",
    "ifmap_shape",
    "matrix_shape",
    "matrix",
    "result_shape",
    "result",
    "toeplitz_shape",
    "toeplitz"
};

int file_descriptors[10];

initial begin
    foreach (files[i]) begin
        file_descriptors[i] = $fopen({files_path,files[i],".txt"},"r");
        if (file_descriptors[i] == 0) begin
            $display("Error opening file %s",files[i]);
            $finish;
        end
    end
end

function int get_index_of_file(string file_name);
    int i;
    for (i=0; i<10; i++) begin
        if (files[i] == file_name) begin
            return i;
        end
    end
endfunction

function int input_files(string file_name);
    return file_descriptors[get_index_of_file(file_name)];
endfunction 

/////////////
// TASKS & TEST SCRIPT
/////////////

int f_ifmap, f_ofmap, f_mapped_matrix;

initial begin
    
    nrst = 0;

    #(CLK_PERIOD*2);
    nrst = 1;
    #(CLK_PERIOD*2);

    csr_main_start = 1;

    while (!$feof(input_files("ifmap"))) begin
        $fscanf(input_files("ifmap"),"%h",f_ifmap);
        $display("ifmap: %h",f_ifmap);
    end
    void'($fseek(input_files("ifmap"),0,0));

    $display("TEST SUCCESS");

    $finish;
end
    
endmodule