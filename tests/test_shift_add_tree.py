"""Unit test for rtl/shift_add_tree.sv covering signed and unsigned weight planes.

Parametrized over `signed` in [False, True] and `B` in [1, 2, 4, 8].
Each case runs Verilator on tb/shift_add_tree/tb_shift_add_tree.sv with the DUT
and asserts exit 0 and 'TB_PASS' in the simulation output.
"""

import subprocess
import os
import pytest

repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

tb_dir = os.path.join(repo_root, 'tb', 'shift_add_tree')
rtl_dir = os.path.join(repo_root, 'rtl')
sims_dir = os.path.join(repo_root, 'sims')

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
    os.makedirs(sims_dir, exist_ok=True)
    log_file = os.path.join(sims_dir, f'tb_shift_add_tree_B{B}_signed{int(signed)}.log')

    verilator_params = [
        f'-GweightBits={B}',
        f'-GweightSigned={int(signed)}',
    ]

    compile_command = [
        'verilator',
        *rtl_files,
        tb_file,
    ] + sim_args_verilator + verilator_params + [
        '--top-module', top_name,
        '-o', f'V{top_name}',
        '--Mdir', f'obj_dir_{top_name}',
    ]

    print(f'=====VERILATOR COMPILE COMMAND (B={B}, signed={signed})=====')
    print(' '.join(compile_command))

    with open(log_file, 'w+') as f:
        proc = subprocess.Popen(
            compile_command,
            shell=False,
            cwd=sims_dir,
            stdout=f,
            stderr=subprocess.STDOUT,
        )
    retval = proc.returncode if proc.poll() is not None else None
    proc.wait()
    retval = proc.returncode
    assert retval == 0, f'Verilator compilation failed for B={B}, signed={signed}; see {log_file}'

    run_command = [f'./obj_dir_{top_name}/V{top_name}']

    print(f'=====VERILATOR RUN COMMAND (B={B}, signed={signed})=====')
    print(' '.join(run_command))

    with open(log_file, 'a') as f:
        f.write('\n===== VERILATOR RUN COMMAND =====\n')
        f.write(' '.join(run_command))
        f.write('\n')
        sim = subprocess.Popen(
            run_command,
            shell=False,
            cwd=sims_dir,
            stdout=f,
            stderr=subprocess.STDOUT,
        )
    sim.wait()
    retval = sim.returncode

    with open(log_file, 'r') as f:
        output = f.read()

    print(output)

    assert retval == 0, f'Simulation failed for B={B}, signed={signed}; see {log_file}'
    assert 'TB_PASS' in output, f'TB_PASS not found in output for B={B}, signed={signed}:\n{output}'
