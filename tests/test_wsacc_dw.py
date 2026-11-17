"""Unit test for rtl/wsacc/wsacc_pe_cluster.sv digital WSAcc depthwise path.

Compiles tb/wsacc/tb_wsacc_dw.sv with verilator (int8 signed weights, 9 taps,
4 PEs, windowElements=9, outputWidth=16) and asserts exit 0 and 'TB_PASS' in
the simulation output. The testbench compares each PE's MAC against a numpy
depthwise sum computed with the same weight/activation layout (PE c receives
byte c of each 32-bit weight word; tap index = weight_addr order).
"""

import subprocess
import os
import pytest

repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

tb_dir = os.path.join(repo_root, 'tb', 'wsacc')
rtl_dir = os.path.join(repo_root, 'rtl')
sims_dir = os.path.join(repo_root, 'sims')

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
    os.makedirs(sims_dir, exist_ok=True)
    log_file = os.path.join(sims_dir, 'tb_wsacc_dw.log')

    verilator_params = [
        '-GnumPes=4',
        '-GwindowElements=9',
        '-GdataWidth=8',
        '-GoutputWidth=16',
        '-GweightInterfaceWidth=32',
    ]

    compile_command = [
        'verilator',
        *rtl_files,
        tb_file,
    ] + sim_args_verilator + verilator_params + [
        '--top-module', top_name,
        '-o', top_name,
        '--Mdir', f'obj_dir_{top_name}',
    ]

    print(f'=====VERILATOR COMPILE COMMAND=====')
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
    assert retval == 0, f'Verilator compilation failed; see {log_file}'

    run_command = [f'./obj_dir_{top_name}/{top_name}']

    print(f'=====VERILATOR RUN COMMAND=====')
    print(' '.join(run_command))

    with open(log_file, 'a') as f:
        f.write('\n===== VERILATOR RUN COMMAND =====\n')
        f.write(' '.join(run_command))
        f.write('\n')
    sim = subprocess.Popen(
        run_command,
        shell=False,
        cwd=sims_dir,
        stdout=open(log_file, 'a'),
        stderr=subprocess.STDOUT,
    )
    sim.wait()
    retval = sim.returncode

    with open(log_file, 'r') as f:
        output = f.read()

    print(output)

    assert retval == 0, f'Simulation failed; see {log_file}'
    assert 'TB_PASS' in output, f'TB_PASS not found in output:\n{output}'
