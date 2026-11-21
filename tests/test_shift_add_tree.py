"""Unit test for rtl/shift_add_tree.sv covering signed and unsigned weight planes.

Parametrized over `signed` in [False, True] and `B` in [1, 2, 4, 8].
Each case runs Verilator on tb/shift_add_tree/tb_shift_add_tree.sv with the DUT
in a private per-test workspace and asserts exit 0 and 'TB_PASS'.
"""

import os
import pytest

from .utils import run_verilator_case

repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

tb_dir = os.path.join(repo_root, 'tb', 'shift_add_tree')
rtl_dir = os.path.join(repo_root, 'rtl')

tb_file = os.path.join(tb_dir, 'tb_shift_add_tree.sv')

rtl_files = [
    os.path.join(rtl_dir, 'shift_add_tree.sv'),
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

top_name = 'tb_shift_add_tree'


@pytest.mark.parametrize("signed", [False, True])
@pytest.mark.parametrize("B", [1, 2, 4, 8])
def test_shift_add_tree(signed, B):
    run_verilator_case(
        tb_file=tb_file,
        rtl_file_list=rtl_files,
        parameter_list={
            'weightBits': B,
            'weightSigned': int(signed),
        },
        top_module=top_name,
        log_name=f'tb_shift_add_tree_B{B}_signed{int(signed)}.log',
        verilator_args=sim_args_verilator,
    )
