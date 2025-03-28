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
    parameter SRAM_ROWS = qrAccInputElements,
    parameter SRAM_COLS = qrAccOutputElements,

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

int i,j,k,l,x,y;

// ======= BEGIN ANALOG SIGNALS =======

logic [numRows-1:0] PSM_VDR_SEL;
logic [numRows-1:0] PSM_VDR_SELB;
logic [numRows-1:0] PSM_VSS_SEL;
logic [numRows-1:0] PSM_VSS_SELB;
logic [numRows-1:0] PSM_VRST_SEL;
logic [numRows-1:0] PSM_VRST_SELB;

logic [numRows-1:0] NSM_VDR_SEL;
logic [numRows-1:0] NSM_VDR_SELB;
logic [numRows-1:0] NSM_VSS_SEL;
logic [numRows-1:0] NSM_VSS_SELB;
logic [numRows-1:0] NSM_VRST_SEL;
logic [numRows-1:0] NSM_VRST_SELB;

logic [numCols-1:0] SA_OUT;
logic [numRows-1:0] WL;
logic PCH;
logic [numCols-1:0] WR_DATA;
logic WRITE;
logic [numCols-1:0] CSEL;
logic SAEN;
logic [compCount*numCols-1:0] ADC_OUT;
logic NF;
logic NFB;
logic M2A;
logic M2AB;
logic R2A;
logic R2AB;
logic CLK;

// We need to do this because
// it's illegal to connect VAMS electrical to structs
assign PSM_VDR_SEL = to_analog.PSM_VDR_SEL;
assign PSM_VDR_SELB = to_analog.PSM_VDR_SELB;
assign PSM_VSS_SEL = to_analog.PSM_VSS_SEL;
assign PSM_VSS_SELB = to_analog.PSM_VSS_SELB;
assign PSM_VRST_SEL = to_analog.PSM_VRST_SEL;
assign PSM_VRST_SELB = to_analog.PSM_VRST_SELB;
assign NSM_VDR_SEL = to_analog.NSM_VDR_SEL;
assign NSM_VDR_SELB = to_analog.NSM_VDR_SELB;
assign NSM_VSS_SEL = to_analog.NSM_VSS_SEL;
assign NSM_VSS_SELB = to_analog.NSM_VSS_SELB;
assign NSM_VRST_SEL = to_analog.NSM_VRST_SEL;
assign NSM_VRST_SELB = to_analog.NSM_VRST_SELB;

assign from_analog.SA_OUT = SA_OUT;
assign WL = to_analog.WL;
assign PCH = to_analog.PCH;
assign WR_DATA = to_analog.WR_DATA;
assign WRITE = to_analog.WRITE;
assign CSEL = to_analog.CSEL;
assign SAEN = to_analog.SAEN;
assign from_analog.ADC_OUT = ADC_OUT;
assign NF = to_analog.NF;
assign NFB = to_analog.NFB;
assign M2A = to_analog.M2A;
assign M2AB = to_analog.M2AB;
assign R2A = to_analog.R2A;
assign R2AB = to_analog.R2AB;
assign CLK = to_analog.CLK;

// ======= END ANALOG SIGNALS =======

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

// Analog test schematic
ts_qracc #(
    .numRows(SRAM_ROWS),
    .numCols(SRAM_COLS),
    .numAdcBits(numAdcBits)
) u_ts_qracc (
    .PSM_VDR_SEL(PSM_VDR_SEL),
    .PSM_VDR_SELB(PSM_VDR_SELB),
    .PSM_VSS_SEL(PSM_VSS_SEL),
    .PSM_VSS_SELB(PSM_VSS_SELB),
    .PSM_VRST_SEL(PSM_VRST_SEL),
    .PSM_VRST_SELB(PSM_VRST_SELB),
    .NSM_VDR_SEL(NSM_VDR_SEL),
    .NSM_VDR_SELB(NSM_VDR_SELB),
    .NSM_VSS_SEL(NSM_VSS_SEL), 
    .NSM_VSS_SELB(NSM_VSS_SELB),
    .NSM_VRST_SEL(NSM_VRST_SEL),
    .NSM_VRST_SELB(NSM_VRST_SELB),
    .SA_OUT(SA_OUT),
    .WL(WL),
    .PCH(PCH),
    .WR_DATA(WR_DATA),
    .WRITE(WRITE),
    .CSEL(CSEL),
    .SAEN(SAEN),
    .ADC_OUT(ADC_OUT),
    .NF(NF),
    .NFB(NFB),
    .M2A(M2A),
    .M2AB(M2AB),
    .R2A(R2A),
    .R2AB(R2AB),
    .CLK(clk)
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

function int get_index_of_file(input string file_name);
    int i;
    for (i=0; i<10; i++) begin
        if (files[i] == file_name) begin
            return i;
        end
    end
endfunction

function int input_files(input string file_name);
    return file_descriptors[get_index_of_file(file_name)];
endfunction 

class NumpyArray;

    int array [];
    int shape [];
    int size = 1;
    string file_name;

    function new (input string file_name);
        this.file_name = file_name;
        read_shape(file_name);
        for (int i=0;i<this.shape.size();i++) begin
            this.size *= this.shape[i];
        end
        this.array = new[this.size];
        read_array(file_name);
    endfunction

    function void read_shape(input string file_name);
        int fd;
        fd = input_files({file_name,"_shape"});
        for (int i=0;!$feof(fd);i++) begin
            this.shape = new[this.shape.size()+1] (this.shape);
            $fscanf(fd,"%d",this.shape[i]);
        end
        this.shape = new[this.shape.size()-1] (this.shape);
        void'($fseek(fd,0,0));
    endfunction

    function void read_array(input string file_name);
        int fd;
        fd = input_files(file_name);
        void'($fseek(fd,0,0));
        for (int i=0;!$feof(fd);i++) begin
            $fscanf(fd,"%d",this.array[i]);
        end
        void'($fseek(fd,0,0));
    endfunction

    function void print_shape();
        $display("Shape: ");
        for (int i=0;i<this.shape.size();i++) begin
            $display("%d",this.shape[i]);
        end
    endfunction

    function void print_array();
        $display("Array: ");
        for (int i=0;i<this.size;i++) begin
            $write("%d\t",this.array[i]);
        end
        $write("\n");
    endfunction

endclass

/////////////
// TASKS & TEST SCRIPT
/////////////

NumpyArray ifmap, ofmap, weight_matrix, toeplitz;

task setup_config();
    cfg.n_input_bits_cfg = 4;
    cfg.binary_cfg = 0;
    cfg.adc_ref_range_shifts = 2;
    
    cfg.filter_size_y = 3;
    cfg.filter_size_x = 3;
    cfg.input_fmap_size = 768;
    cfg.output_fmap_size = 768;
    cfg.input_fmap_dimx = 16;
    cfg.input_fmap_dimy = 16;
    cfg.output_fmap_dimx = 16;
    cfg.output_fmap_dimy = 16;

    cfg.num_input_channels = 3;
    cfg.num_output_channels = 32;
endtask

task start_sim();

    cfg = 0;
    csr_main_busy = 0;
    csr_main_clear = 0;
    csr_main_inst_write_mode = 0;
    csr_main_start = 0;

    bus.wen = 0;
    bus.valid = 0;
    bus.addr = 0;
    bus.data_in = 0;
    periph.wen = 0;
    periph.valid = 0;
    periph.addr = 0;
    periph.data = 0;

    $display("=============== STARTING SIMULATION ===============");
    nrst = 0;
    #(CLK_PERIOD*2);
    nrst = 1;
    #(CLK_PERIOD*2);
endtask

task load_weights();

    $write("Loading weights");
    for (i=0;i<qrAccInputElements;i++) begin
        bus.data_in = weight_matrix.array[i];
        bus.valid = 1;
        bus.wen = 1;
        while (!bus.ready) #(CLK_PERIOD);
        #(CLK_PERIOD);
        $write(".");
        bus.valid = 0;
    end
    $write("\n");

endtask

task check_weights();

    for (i=0;i<qrAccInputElements;i++) begin
        $write("[%d]:\t",i);
        $display("%b\t",u_ts_qracc.mem[i]);
        if (u_ts_qracc.mem[i] != weight_matrix.array[i]) begin
            $display("Weight mismatch at index %d: %d != %d",i,u_ts_qracc.mem[i],weight_matrix.array[i]);
            $finish;
        end
    end

endtask

task load_acts();

    $write("Loading activations");
    for (i=0;i<ifmap.size;i++) begin
        bus.data_in = ifmap.array[i];
        bus.valid = 1;
        while (!bus.ready) begin
            #(CLK_PERIOD);
        end
        $write(".");
        bus.valid = 0;
    end
    $write("\n");

endtask

task load_scales();

    // TBI

endtask

initial begin
    ifmap = new("ifmap");
    ofmap = new("result");
    weight_matrix = new("matrix");
    toeplitz = new("toeplitz");

    // Setup monitors
    $monitor("[MONITOR] controller state:%d",u_qr_acc_top.u_qracc_controller.state_q);

    start_sim();

    setup_config();

    #(CLK_PERIOD*2);
    csr_main_start = 1;

    // weight_matrix.print_array();

    load_weights();

    check_weights();

    #(CLK_PERIOD*1000);

    $display("TEST SUCCESS");
    $display("=============== END OF SIMULATION ===============");

    $finish;
end
    
endmodule