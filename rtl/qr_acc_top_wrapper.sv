/* 
n-Bit input DNN accelerator
uses n cycles to complete an n-bit input mac
asdasd
*/

`include "qracc_params.svh"

`timescale 1ns/1ps

import qracc_pkg::*;

module qr_acc_top_wrapper #(

    //  Parameters: Interface
    parameter dataInterfaceSize = 32,
    parameter ctrlInterfaceSize = 32,

    //  Parameters: QRAcc
    parameter qrAccInputBits = 8,
    parameter qrAccInputElements = 256,
    parameter qrAccOutputBits = 8,
    parameter qrAccOutputElements = 256,
    parameter qrAccAdcBits = 4,
    parameter qrAccAccumulatorBits = 16, // Internal parameter of seq acc

    //  Parameters: Per Bank
    parameter numRows = 256,
    parameter numCols = 32,
    parameter numBanks = 256/numCols,

    //  Parameters: Global Buffer
    parameter globalBufferDepth = 2**8,
    parameter globalBufferExtInterfaceWidth = 32,
    parameter globalBufferIntInterfaceWidth = 256,
    parameter globalBufferAddrWidth = 32,
    parameter globalBufferDataSize = 8,          // Byte-Addressability

    // Parameters: Feature Loader
    parameter aflDimY = 128,
    parameter aflDimX = 6,
    parameter aflAddrWidth = 32,
    parameter featureLoaderNumElements = 9*32, // We need 32 windows for WSAcc

    // Parameters: WSAcc
    parameter wsAccNumPes = 32, // Number of PEs in WSAcc
    parameter wsAccWindowElements = 9, // Number of elements in the WSAcc window

    // Parameters: Addressing
    parameter csrBaseAddr = 32'h0000_0010, // Base address for CSR
    parameter accBaseAddr = 32'h0000_0100 // Base address for Accelerator
) (
    input clk, nrst,

    // Bus Interface
    input  logic [31:0] bus_data_in,
    input  logic [31:0] bus_addr,
    input  logic        bus_wen,
    input  logic        bus_valid,
    output logic        bus_ready,
    output logic [31:0] bus_data_out,
    output logic        bus_rd_data_valid,

    // Analog passthrough signals
    // output to_analog_t to_analog,
    // input from_analog_t from_analog,
    output logic [numRows-1:0] to_analog_PSM_VDR_SEL,
    output logic [numRows-1:0] to_analog_PSM_VDR_SELB,
    output logic [numRows-1:0] to_analog_PSM_VSS_SEL,
    output logic [numRows-1:0] to_analog_PSM_VSS_SELB,
    output logic [numRows-1:0] to_analog_PSM_VRST_SEL,
    output logic [numRows-1:0] to_analog_PSM_VRST_SELB,
    output logic [numRows-1:0] to_analog_NSM_VDR_SEL,
    output logic [numRows-1:0] to_analog_NSM_VDR_SELB,
    output logic [numRows-1:0] to_analog_NSM_VSS_SEL,
    output logic [numRows-1:0] to_analog_NSM_VSS_SELB,
    output logic [numRows-1:0] to_analog_NSM_VRST_SEL,
    output logic [numRows-1:0] to_analog_NSM_VRST_SELB,
    output logic [numRows-1:0] to_analog_WL,
    output logic to_analog_PCH,
    output logic [numCols-1:0] to_analog_WR_DATA,
    output logic to_analog_WRITE,
    output logic [numCols-1:0] to_analog_CSEL,
    output logic to_analog_SAEN,
    output logic to_analog_NF,
    output logic to_analog_NFB,
    output logic to_analog_M2A,
    output logic to_analog_M2AB,
    output logic to_analog_R2A,
    output logic to_analog_R2AB,
    output logic to_analog_CLK,

    input logic [numCols-1:0] from_analog_SA_OUT,
    input logic [479:0] from_analog_ADC_OUT,
    output [numBanks-1:0] bank_select
);

    qracc_data_interface bus();
    to_analog_t to_analog;
    from_analog_t from_analog;

    assign bus.data_in = bus_data_in;
    assign bus.addr = bus_addr;
    assign bus.wen = bus_wen;
    assign bus.valid = bus_valid;
    assign bus_ready = bus.ready;
    assign bus_data_out = bus.data_out;
    assign bus_rd_data_valid = bus.rd_data_valid;

    assign from_analog.SA_OUT = from_analog_SA_OUT;
    assign from_analog.ADC_OUT = from_analog_ADC_OUT;

    assign to_analog_PSM_VDR_SEL = to_analog.PSM_VDR_SEL;
    assign to_analog_PSM_VDR_SELB = to_analog.PSM_VDR_SELB;
    assign to_analog_PSM_VSS_SEL = to_analog.PSM_VSS_SEL;
    assign to_analog_PSM_VSS_SELB = to_analog.PSM_VSS_SELB;
    assign to_analog_PSM_VRST_SEL = to_analog.PSM_VRST_SEL;
    assign to_analog_PSM_VRST_SELB = to_analog.PSM_VRST_SELB;
    assign to_analog_NSM_VDR_SEL = to_analog.NSM_VDR_SEL;
    assign to_analog_NSM_VDR_SELB = to_analog.NSM_VDR_SELB;
    assign to_analog_NSM_VSS_SEL = to_analog.NSM_VSS_SEL;
    assign to_analog_NSM_VSS_SELB = to_analog.NSM_VSS_SELB;
    assign to_analog_NSM_VRST_SEL = to_analog.NSM_VRST_SEL;
    assign to_analog_NSM_VRST_SELB = to_analog.NSM_VRST_SELB;
    assign to_analog_WL = to_analog.WL;
    assign to_analog_PCH = to_analog.PCH;
    assign to_analog_WR_DATA = to_analog.WR_DATA;
    assign to_analog_WRITE = to_analog.WRITE;
    assign to_analog_CSEL = to_analog.CSEL;
    assign to_analog_SAEN = to_analog.SAEN;
    assign to_analog_NF = to_analog.NF;
    assign to_analog_NFB = to_analog.NFB;
    assign to_analog_M2A = to_analog.M2A;
    assign to_analog_M2AB = to_analog.M2AB;
    assign to_analog_R2A = to_analog.R2A;
    assign to_analog_R2AB = to_analog.R2AB;
    assign to_analog_CLK = to_analog.CLK;

    qr_acc_top #(
        .dataInterfaceSize(dataInterfaceSize),
        .ctrlInterfaceSize(ctrlInterfaceSize),
        .qrAccInputBits(qrAccInputBits),
        .qrAccInputElements(qrAccInputElements),
        .qrAccOutputBits(qrAccOutputBits),
        .qrAccOutputElements(qrAccOutputElements),
        .qrAccAdcBits(qrAccAdcBits),
        .qrAccAccumulatorBits(qrAccAccumulatorBits),
        .numRows(numRows),
        .numCols(numCols),
        .numBanks(numBanks),
        .globalBufferDepth(globalBufferDepth),
        .globalBufferExtInterfaceWidth(globalBufferExtInterfaceWidth),
        .globalBufferIntInterfaceWidth(globalBufferIntInterfaceWidth),
        .globalBufferAddrWidth(globalBufferAddrWidth),
        .globalBufferDataSize(globalBufferDataSize),
        .aflDimY(aflDimY),
        .aflDimX(aflDimX),
        .aflAddrWidth(aflAddrWidth),
        .featureLoaderNumElements(featureLoaderNumElements),
        .wsAccNumPes(wsAccNumPes),
        .wsAccWindowElements(wsAccWindowElements),
        .csrBaseAddr(csrBaseAddr),
        .accBaseAddr(accBaseAddr)
    ) u_qr_acc_top (
        .clk(clk),
        .nrst(nrst),
        .bus_i(bus.slave),
        .to_analog(to_analog),
        .from_analog(from_analog),
        .bank_select(bank_select)
    );

endmodule
