"""Bit-exact write-path test for rtl/wr_controller.sv.

Parametrized over `wr_bus_sel` in [0, 1, 2] (32B / 64B / 128B beats).
Each case builds and runs tb/wr_path/tb_wr_path.sv with Verilator and
asserts exit 0 and 'TB_PASS' in the simulation output.
"""

import subprocess
import os
import pytest

repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

tb_dir = os.path.join(repo_root, 'tb', 'wr_path')
rtl_dir = os.path.join(repo_root, 'rtl')
sims_dir = os.path.join(repo_root, 'sims')

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
    os.makedirs(sims_dir, exist_ok=True)
    log_file = os.path.join(sims_dir, f'tb_wr_path_wr_bus_sel{wr_bus_sel}.log')

    verilator_params = [
        f'-GwrBusSel={wr_bus_sel}',
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

    print(f'=====VERILATOR COMPILE COMMAND (wr_bus_sel={wr_bus_sel})=====')
    print(' '.join(compile_command))

    with open(log_file, 'w+') as f:
        proc = subprocess.Popen(
            compile_command,
            shell=False,
            cwd=sims_dir,
            stdout=f,
            stderr=subprocess.STDOUT,
        )
    proc.wait()
    retval = proc.returncode
    assert retval == 0, f'Verilator compilation failed for wr_bus_sel={wr_bus_sel}; see {log_file}'

    run_command = [f'./obj_dir_{top_name}/V{top_name}']

    print(f'=====VERILATOR RUN COMMAND (wr_bus_sel={wr_bus_sel})=====')
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

    assert retval == 0, f'Simulation failed for wr_bus_sel={wr_bus_sel}; see {log_file}'
    assert 'TB_PASS' in output, f'TB_PASS not found in output for wr_bus_sel={wr_bus_sel}:\n{output}'
