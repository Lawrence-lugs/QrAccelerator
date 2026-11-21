"""Bit-exact write-path test for rtl/wr_controller.sv.

Parametrized over `wr_bus_sel` in [0, 1, 2] (32B / 64B / 128B beats).
Each case builds and runs tb/wr_path/tb_wr_path.sv in a private per-test
workspace and asserts exit 0 and 'TB_PASS'.
"""

import os
import pytest

from .utils import run_verilator_case

repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

tb_dir = os.path.join(repo_root, 'tb', 'wr_path')
rtl_dir = os.path.join(repo_root, 'rtl')

tb_file = os.path.join(tb_dir, 'tb_wr_path.sv')

rtl_files = [
    os.path.join(rtl_dir, 'qracc_pkg.svh'),
    os.path.join(rtl_dir, 'wr_controller.sv'),
]

sim_args_verilator = [
    '+define+QRACC_PARAMS_FILE="qracc_params.svh"',
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

top_name = 'tb_wr_path'


@pytest.mark.parametrize("wr_bus_sel", [0, 1, 2])
def test_wr_path(wr_bus_sel):
    run_verilator_case(
        tb_file=tb_file,
        rtl_file_list=rtl_files,
        parameter_list={'wrBusSel': wr_bus_sel},
        top_module=top_name,
        log_name=f'tb_wr_path_wr_bus_sel{wr_bus_sel}.log',
        verilator_args=sim_args_verilator,
    )
