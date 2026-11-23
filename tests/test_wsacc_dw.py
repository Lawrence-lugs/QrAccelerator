"""Unit test for rtl/wsacc/wsacc_pe_cluster.sv digital WSAcc depthwise path.

Compiles tb/wsacc/tb_wsacc_dw.sv with verilator (int8 signed weights, 9 taps,
4 PEs, windowElements=9, outputWidth=16) in a private per-test workspace and
asserts exit 0 and 'TB_PASS'. The testbench compares each PE's MAC against a
numpy depthwise sum computed with the same weight/activation layout (PE c
receives byte c of each 32-bit weight word; tap index = weight_addr order).
"""

import os
import pytest

from .utils import run_verilator_case

repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

tb_dir = os.path.join(repo_root, 'tb', 'wsacc')
rtl_dir = os.path.join(repo_root, 'rtl')

tb_file = os.path.join(tb_dir, 'tb_wsacc_dw.sv')

rtl_files = [
    os.path.join(rtl_dir, 'wsacc', 'wsacc_pe_cluster.sv'),
    os.path.join(rtl_dir, 'wsacc', 'wsacc_pe.sv'),
]

sim_args_verilator = [
    '--binary',
    '--timing',
    '-j', '4',
    '-sv',
    '+incdir+../rtl',
    '-Wno-fatal',
    '-Wno-WIDTHEXPAND',
    '-Wno-WIDTHTRUNC',
    '-Wno-UNUSEDSIGNAL',
    '-Wno-UNDRIVEN',
    '-Wno-UNUSEDPARAM',
    '-Wno-PINMISSING',
    '-Wno-GENUNNAMED',
    '-Wno-CASEINCOMPLETE',
    '-Wno-TIMESCALEMOD',
    '-Wno-IMPLICITSTATIC',
    '-Wno-LATCH',
    '-Wno-COMBDLY',
    '-Wno-BLKSEQ',
    '-Wno-INITIALDLY',
    '-CFLAGS', '-O1',
]

top_name = 'tb_wsacc_dw'


def test_wsacc_dw():
    run_verilator_case(
        tb_file=tb_file,
        rtl_file_list=rtl_files,
        parameter_list={
            'numPes': 4,
            'windowElements': 9,
            'dataWidth': 8,
            'outputWidth': 16,
            'weightInterfaceWidth': 32,
        },
        top_module=top_name,
        log_name='tb_wsacc_dw.log',
        verilator_args=sim_args_verilator,
    )
