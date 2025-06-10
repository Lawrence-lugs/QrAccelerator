`timescale 1ns/1ps

import qracc_pkg::*;

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
    parameter qrAccInputBits = `QRACC_INPUT_BITS,
    parameter qrAccInputElements = `SRAM_ROWS,
    parameter qrAccOutputBits = `QRACC_OUTPUT_BITS,
    parameter qrAccOutputElements = `SRAM_COLS,
    parameter qrAccAdcBits = 4,
    parameter qrAccAccumulatorBits = 16, // Internal parameter of seq acc
    
    //  Parameters: Per Bank
    parameter numRows = `SRAM_ROWS,
    parameter numCols = 32,
    parameter numBanks = `SRAM_COLS/numCols,

    //  Parameters: Global Buffer
    parameter globalBufferDepth = 2**21,
    parameter globalBufferExtInterfaceWidth = 32,
    parameter globalBufferIntInterfaceWidth = `GB_INT_IF_WIDTH,
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
logic [numBanks-1:0] bank_select;

qracc_config_t cfg;
logic csr_main_clear;
qracc_trigger_t csr_main_trigger;
logic csr_main_busy;
logic csr_main_inst_write_mode;

enum { 
    S_START,
    S_LOADWEIGHTS,
    S_LOADACTS,
    S_LOADBIAS,
    S_LOADSCALE,
    S_COMPUTE
} tb_state;

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
logic [compCount*qrAccOutputElements-1:0] ADC_OUT;
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

    .numRows                        (numRows),
    .numCols                        (numCols),
    .numBanks                       (numBanks),

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
    .bus_i                          (bus.slave), 

    // Analog passthrough signals
    .to_analog                      (to_analog),
    .from_analog                    (from_analog),
    .bank_select                    (bank_select)
);

// Analog test schematic
ts_qracc_multibank #(
    .numRows(qrAccInputElements),
    .numCols(numCols),
    .numAdcBits(numAdcBits),
    .numBanks(numBanks)
) u_ts_qracc (
    .bank_select(bank_select),
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
static string output_path = "/home/lquizon/lawrence-workspace/SRAM_test/qrAcc2/qr_acc_2_digital/tb/qracc_top/outputs/";
static string tb_name = "tb_qracc_top";

// Waveform Dumping
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
    #(100_000_0); // 100 ms
    $display("TEST FAILED - WATCHDOG TIMEOUT");
    $finish;
end

/////////////
// FILE THINGS
/////////////

localparam numFiles = 13;
string files[numFiles] = {
    "ifmap",
    "ifmap_shape",
    "matrix_shape",
    "matrix",
    "result_shape",
    "result",
    "toeplitz_shape",
    "toeplitz",
    "scaler_data_shape",
    "scaler_data",
    "biases",
    "biases_shape",
    "config"
};
int file_descriptors[numFiles];

initial begin
    $display("=== FILE LIST ===");
    foreach (files[i]) begin
        $display("%d: %s",i,files[i]);
        file_descriptors[i] = $fopen({files_path,files[i],".txt"},"r");
        if (file_descriptors[i] == 0) begin
            $display("Error opening file %s",files[i]);
            $finish;
        end
    end
end

function int get_index_of_file(input string file_name);
    int i;
    foreach (files[i]) begin
        if (files[i] == file_name) begin
            return i;
        end
    end
endfunction

function int input_files(input string file_name);
    // $display("Opening file %s at %d",file_name,get_index_of_file(file_name));
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
        $display("==== Array ====");
        $display("%s: %d",file_name,this.size);
        $display("Shape: ");
        for (int i=0;i<this.shape.size();i++) begin
            $display("%d",this.shape[i]);
        end
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

    function int index (
        input int idx[]
    );
        // Accesses array indices like array.index( {3,2,1 } ) similar to numpy array[3][2][1]

        int flat_index;
        flat_index = 0;
        // $write("[ARRAY %s] Accessing indices ", this.file_name);
        for (int i=0;i<this.shape.size();i++) begin
            // $write("%d ",idx[i]);
            if (i == 0)
                flat_index = idx[i];
            else
                flat_index = flat_index * this.shape[i] + idx[i];
        end
        // $write("\t Flat index of %d\n", flat_index);
        if (flat_index < 0) begin
            $display("[ARRAY] Negative index: %d", flat_index);
            return -1;
        end
        
        // if (flat_index >= this.size) begin
        //     $display("[ARRAY] Index out of bounds: %d", flat_index);
        //     return -1;
        // end
        return this.array[flat_index];
    endfunction

endclass

/////////////
// TASKS & TEST SCRIPT
/////////////

NumpyArray ifmap, ofmap, weight_matrix, toeplitz, scaler_data, biases;
int errcnt = 0;

task setup_config_from_file(int fd);

    // Read the config file
    $fscanf(fd,"n_input_bits_cfg: %d\n",cfg.n_input_bits_cfg);
    $fscanf(fd,"n_output_bits_cfg: %d\n",cfg.n_output_bits_cfg);
    $fscanf(fd,"unsigned_acts: %d\n",cfg.unsigned_acts);
    $fscanf(fd,"binary_cfg: %d\n",cfg.binary_cfg);
    $fscanf(fd,"adc_ref_range_shifts: %d\n",cfg.adc_ref_range_shifts);

    $fscanf(fd,"filter_size_y: %d\n",cfg.filter_size_y);
    $fscanf(fd,"filter_size_x: %d\n",cfg.filter_size_x);
    $fscanf(fd,"input_fmap_dimx: %d\n",cfg.input_fmap_dimx);
    $fscanf(fd,"input_fmap_dimy: %d\n",cfg.input_fmap_dimy);
    $fscanf(fd,"output_fmap_dimx: %d\n",cfg.output_fmap_dimx);
    $fscanf(fd,"output_fmap_dimy: %d\n",cfg.output_fmap_dimy);

    $fscanf(fd,"stride_x: %d\n",cfg.stride_x);
    $fscanf(fd,"stride_y: %d\n",cfg.stride_y);

    $fscanf(fd,"num_input_channels: %d\n",cfg.num_input_channels);
    $fscanf(fd,"num_output_channels: %d\n",cfg.num_output_channels);

    $fscanf(fd,"mapped_matrix_offset_x: %d\n",cfg.mapped_matrix_offset_x);
    $fscanf(fd,"mapped_matrix_offset_y: %d\n",cfg.mapped_matrix_offset_y);

endtask

task setup_config();
    cfg.n_input_bits_cfg = `QRACC_INPUT_BITS;
    cfg.n_output_bits_cfg = `QRACC_OUTPUT_BITS;
    cfg.unsigned_acts = `UNSIGNED_ACTS;

    cfg.binary_cfg = 1;
    cfg.adc_ref_range_shifts = `NUM_ADC_REF_RANGE_SHIFTS;
    
    cfg.filter_size_y = `FILTER_SIZE_Y;
    cfg.filter_size_x = `FILTER_SIZE_X;
    cfg.input_fmap_dimx = `IFMAP_DIMX;
    cfg.input_fmap_dimy = `IFMAP_DIMY;
    cfg.output_fmap_dimx = `OFMAP_DIMX;
    cfg.output_fmap_dimy = `OFMAP_DIMY;

    cfg.stride_x = `STRIDE_X;
    cfg.stride_y = `STRIDE_Y;

    cfg.num_input_channels = `IN_CHANNELS;
    cfg.num_output_channels = `OUT_CHANNELS;

    cfg.mapped_matrix_offset_x = `MAPPED_MATRIX_OFFSET_X;
    cfg.mapped_matrix_offset_y = `MAPPED_MATRIX_OFFSET_Y;
endtask

assign cfg = u_qr_acc_top.cfg;

task display_config();

    $display("=== CONFIGURATION ===");
    $display("n_input_bits_cfg: %d", u_qr_acc_top.cfg.n_input_bits_cfg);
    $display("n_output_bits_cfg: %d", u_qr_acc_top.cfg.n_output_bits_cfg);
    $display("unsigned_acts: %d", u_qr_acc_top.cfg.unsigned_acts);
    $display("binary_cfg: %d", u_qr_acc_top.cfg.binary_cfg);
    $display("adc_ref_range_shifts: %d", u_qr_acc_top.cfg.adc_ref_range_shifts);

    $display("filter_size_y: %d", u_qr_acc_top.cfg.filter_size_y);
    $display("filter_size_x: %d", u_qr_acc_top.cfg.filter_size_x);
    $display("input_fmap_dimx: %d", u_qr_acc_top.cfg.input_fmap_dimx);
    $display("input_fmap_dimy: %d", u_qr_acc_top.cfg.input_fmap_dimy);
    $display("output_fmap_dimx: %d", u_qr_acc_top.cfg.output_fmap_dimx);
    $display("output_fmap_dimy: %d", u_qr_acc_top.cfg.output_fmap_dimy);

    $display("stride_x: %d", u_qr_acc_top.cfg.stride_x);
    $display("stride_y: %d", u_qr_acc_top.cfg.stride_y);

    $display("num_input_channels: %d", u_qr_acc_top.cfg.num_input_channels);
    $display("num_output_channels: %d", u_qr_acc_top.cfg.num_output_channels);

    $display("mapped_matrix_offset_x: %d", u_qr_acc_top.cfg.mapped_matrix_offset_x);
    $display("mapped_matrix_offset_y: %d", u_qr_acc_top.cfg.mapped_matrix_offset_y);

endtask

task start_sim();

    // errcnt = 0;

    // SRAM_COLS must be multiple of 32
    if (qrAccInputElements % 32 != 0) begin
        $display("Error: SRAM_COLS must be multiple of 32");
        $finish;
    end

    bus.wen = 0;
    bus.valid = 0;
    bus.addr = 0;
    bus.data_in = 0;

    $display("=============== STARTING SIMULATION ===============");
    nrst = 0;
    #(CLK_PERIOD*2);
    nrst = 1;
    #(CLK_PERIOD*2);
endtask

task status_checkup();
    $display("STATE: %s", u_qr_acc_top.u_qracc_controller.state_q.name());
endtask

task bus_write_loop();

    int fd;
    int data;
    int addr;
    int i;
    fd = $fopen({files_path,"writes.txt"},"r");
    
    $display("=========== BUS WRITE LOOP ============");
    if (fd == 0) begin
        $display("Error opening writes file");
        $finish;
    end

    while (!$feof(fd)) begin
        $fscanf(fd,"%h %h",addr,data);
        casex(addr)
            32'h0000_001x: $write("Writing to CSR: %h = %h", addr, data);
            32'h0000_0100: $write("Writing to QRAcc: %h = %h", addr, data);
            default: $write("Writing to unknown address: %h = %h", addr, data);
        endcase
        bus.addr = addr;
        bus.data_in = data;
        bus.valid = 1;
        bus.wen = 1;
        if(!$feof(fd)) begin
            while (!bus.ready) begin 
                #(CLK_PERIOD);
                $write(".");
            end
            #(CLK_PERIOD);
            $write("\tDONE\n");
            bus.valid = 0;
            status_checkup();
        end
    end

    $write("\n");
    $display("=========== END OF BUS WRITE LOOP ============");

endtask

task load_weights();

    tb_state = S_LOADWEIGHTS;
    $display("Loading weights at time %t", $time);
    for (i=0;i<qrAccInputElements*numBanks;i++) begin
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

    // Check weights doesn't work for multibank, because we're trying to access inside.

    // $display("Checking weights at time %t", $time);
    // for (i=0;i<qrAccInputElements;i++) begin
    //     if (i%4 == 0) begin
    //         $write("\n");
    //         $write("[%d]:\t",i);
    //     end else begin
    //         $write("\t");
    //     end

    //     $write("%h\t",u_ts_qracc.mem[i]);
    //     if (u_ts_qracc..mem[i] != weight_matrix.array[i]) begin
    //         $write(" != %h",weight_matrix.array[i]);
    //         errcnt++;
    //     end
    // end
    // $write("\n");

endtask

task load_acts();

    tb_state = S_LOADACTS;

    $display("Loading activations at time %t", $time);
    for (i=0;i<ifmap.size;i++) begin
        bus.data_in = ifmap.array[i];
        bus.valid = 1;
        bus.wen = 1;
        while (!bus.ready) #(CLK_PERIOD);
        #(CLK_PERIOD);
        $write(".");
        bus.valid = 0;
    end
    $write("\n");

endtask

// Address by 4-byte word
task check_acts();
    int ptr;
    int word;
    ptr = u_qr_acc_top.u_qracc_controller.ifmap_start_addr;

    $display("Checking activations at time %t", $time);
    for (i=0;i<ifmap.size*4;i=i+4) begin
        if (i%16 == 0) begin
            $write("\n");
            $write("[%d]:\t",i);
        end else begin
            $write("\t");
        end
        
        word = {u_qr_acc_top.u_activation_buffer.mem[ptr + i], 
                u_qr_acc_top.u_activation_buffer.mem[ptr + i + 1],
                u_qr_acc_top.u_activation_buffer.mem[ptr + i + 2],
                u_qr_acc_top.u_activation_buffer.mem[ptr + i + 3]};
        
        $write("%h\t",word);
        if (word != ifmap.array[i >> 2]) begin
            $write(" != %h",ifmap.array[i >> 2]);
            errcnt++;
        end
    end
    $write("\n");


endtask

localparam MAX_TROWS = 260;

task track_toeplitz();

    int trow, tplitz_offset, tplitz_height, reference;
    logic errflag;


    tb_state = S_COMPUTE;
    errflag = 0;
    trow = 0;
    tplitz_offset = {16'b0,cfg.mapped_matrix_offset_y};
    tplitz_height = cfg.filter_size_y * cfg.filter_size_x * cfg.num_input_channels;

    // Track only during compute state
    while(u_qr_acc_top.u_qracc_controller.state_q == u_qr_acc_top.u_qracc_controller.S_COMPUTE_ANALOG) begin

        if (trow >= MAX_TROWS) begin
            $display("ERROR: Reached maximum number of rows (%d). Stopping tracking.", MAX_TROWS);
            $finish;
        end

        // Track only when the MAC input is accepted by the seq_acc
        if(u_qr_acc_top.qracc_ctrl.qracc_mac_data_valid && u_qr_acc_top.qracc_ready) begin
            $write("Window [%d][%d,%d]: \n", trow, u_qr_acc_top.u_qracc_controller.opix_pos_x, u_qr_acc_top.u_qracc_controller.opix_pos_y);
            
            // Produces a -- pattern for irrelevant activations
            for (j=0;j<qrAccInputElements;j++) begin
                if (j >= tplitz_offset && j < tplitz_offset + tplitz_height) begin
                    reference  = toeplitz.index( {trow,j-tplitz_offset} );
                    $write("%h",u_qr_acc_top.qracc_mac_data[j]);
                    if (u_qr_acc_top.qracc_mac_data[j] != reference[7:0]) begin
                        $write("!");
                        errflag = 1;
                        errcnt++;
                    end else begin
                        $write(" ");
                    end
                end else begin
                    $write("-- ");
                end
            end
            $write("\n");

            // If error, print the reference 
            if (errflag) begin
                $write("===================== WRONG ====================: at time %d\n",$time);
                for (j=0;j<qrAccInputElements;j++) begin
                    if (j >= tplitz_offset && j < tplitz_offset + tplitz_height) begin
                        reference  = toeplitz.index( {trow,j-tplitz_offset} );
                        $write("%h ",reference[7:0]);
                    end else begin
                        $write("-- ");
                    end
                end
                $write("\n");
                errflag=0;
            end
            trow++;
        end

        #(CLK_PERIOD);
    end

endtask

task load_biases();

    tb_state = S_LOADBIAS;

    $display("Loading biases at time %t", $time);
    for (i=0;i<biases.size;i++) begin
        // $display("[%d]:\t",i);
        bus.data_in = biases.array[i];
        bus.valid = 1;
        bus.wen = 1;
        while (!bus.ready) #(CLK_PERIOD);
        #(CLK_PERIOD);
        $write(".");
        bus.valid = 0;
    end
    $write("\n");

endtask

task load_scales();

    tb_state = S_LOADSCALE;

    $display("Loading scaler data at time %t", $time);
    for (i=0;i<scaler_data.size;i++) begin
        // $display("[%d]:\t",i);
        bus.data_in = scaler_data.array[i];
        bus.valid = 1;
        bus.wen = 1;
        while (!bus.ready) #(CLK_PERIOD);
        #(CLK_PERIOD);
        $write(".");
        bus.valid = 0;
    end
    $write("\n");

endtask

task check_scales();
    logic [15:0] scale;
    logic [3:0] shift;
    logic signed [31:0] bias;
    logic [15:0] scaleref;
    logic [3:0] shiftref;
    logic signed [31:0] biasref;
    $display("Checking scales at time %t", $time);

    for (i=0;i<scaler_data.size;i++) begin
        // if (i%4 == 0) begin
        //     $write("\n");
        //     $write("[%d]:\t",i);
        // end else begin
        //     $write("\t");
        // end
        $write("[%d]:\t",i);
        scale = u_qr_acc_top.u_output_scaler_set.output_scale[i];
        shift = u_qr_acc_top.u_output_scaler_set.output_shift[i];
        bias = u_qr_acc_top.u_output_scaler_set.output_bias[i];
        
        scaleref = scaler_data.array[i][4+:16];
        shiftref = scaler_data.array[i][0+:4];
        biasref = biases.array[i];
        $write("%d\t, %d\t, %d\t",scale,shift,bias);
        if (scale != scaleref | shift != shiftref | bias != biasref) begin
            $write(" != %d, %d, %d",scaleref, shiftref, biasref);
            errcnt++;
        end
        $write("\n");
    end
    $write("\n");

endtask

task end_sim();
    if (errcnt == 0) begin
        $display("TEST SUCCESS");
    end else begin
        $display("TEST FAILED - ERRORS: %d",errcnt);
    end
    $display("=============== END OF SIMULATION ===============");

    $finish;
endtask

task export_ofmap();

    // Magically export of the ofmap without actual readout

    int a;
    int fd;
    int ofmap_size;

    ofmap_size = cfg.output_fmap_dimx * cfg.output_fmap_dimy * cfg.num_output_channels;

    $display("Exporting ofmap at time %t", $time);

    fd = $fopen({output_path,"hw_ofmap",".txt"},"w");
    for(i=0;i<ofmap_size;i++) begin
        // Later on this would be wrong if the output isn't 8b
        // and the 4b or 2b version is packed.
        if (cfg.unsigned_acts) begin
            a = u_qr_acc_top.u_activation_buffer.mem[u_qr_acc_top.u_qracc_controller.ifmap_start_addr + i];
        end else begin
            a = $signed(u_qr_acc_top.u_activation_buffer.mem[u_qr_acc_top.u_qracc_controller.ifmap_start_addr + i]);
        end
        $fwrite(fd,"%d\n",a);
    end

endtask

task do_trigger_loadweights_periphs();
    csr_main_trigger = TRIGGER_LOADWEIGHTS_PERIPHS;
    #(CLK_PERIOD);
    csr_main_trigger = TRIGGER_IDLE;
    load_weights();
    load_scales();
    load_biases();
endtask

task do_trigger_loadacts();
    csr_main_trigger = TRIGGER_LOAD_ACTIVATION;
    #(CLK_PERIOD);
    csr_main_trigger = TRIGGER_IDLE;
    load_acts();
endtask

task do_trigger_compute_analog();
    csr_main_trigger = TRIGGER_COMPUTE_ANALOG;
    #(CLK_PERIOD);
    csr_main_trigger = TRIGGER_IDLE;
    track_toeplitz();
endtask

initial begin
    $display("=============== TESTBENCH START ===============");

    ifmap = new("ifmap");
    ofmap = new("result");
    weight_matrix = new("matrix");
    toeplitz = new("toeplitz");
    scaler_data = new("scaler_data");
    biases = new("biases");

    start_sim();

    bus_write_loop();

    display_config();

    track_toeplitz();

    export_ofmap();

    end_sim();

    $finish;
end
    
endmodule