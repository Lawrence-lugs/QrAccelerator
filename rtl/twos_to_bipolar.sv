module twos_to_bipolar #(
    parameter nBits = 4;
) (
    input logic [nBits-1:0] twos,
    output logic [nBits-1:0] bipolar_p,
    output logic [nBits-1:0] bipolar_n
);

    assign bipolar_p = twos[nBits-1] ? -twos : twos;
    assign bipolar_n = twos[nBits-1] ? twos : -twos;

endmodule