"""Per-test simulation workspaces.

The RTL testbenches and the simulator drivers use a mixture of relative paths
(``../rtl``, ``../tb/<block>/inputs``) and bare output names (``obj_dir_<top>``,
``tb_<top>.vcd``).  Those paths only work while the process working directory is
the repository root and while no two tests write the same file.

This module gives every pytest test its own private tree::

    sims/runs/<run-id>/
        rtl/                 # copy of rtl/, with a private qracc_params.svh
        tb/<block>/          # copy of tb/<block>/, with empty inputs/outputs
        sims/                # cwd for compilers/simulators (obj_dir, dumps)
        logs/                # simulation logs

``run-id`` comes from the pytest node id plus the process id, so concurrent
pytest processes (pytest-xdist or two plain ``pytest`` invocations) never share
files.  The tree is created lazily: Python-only tests never touch the disk.
"""

from __future__ import annotations

import contextvars
import hashlib
import os
import re
import shutil
import threading
import uuid

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_SIM_RUN_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    'qracc_sim_run_id', default=None)

# Protect the one-time copies when tests are driven by threads.  The lock is
# per process; separate pytest processes have separate workspaces anyway.
_WORKSPACE_LOCK = threading.Lock()


def _sanitize_run_id(value: str) -> str:
    safe = re.sub(r'[^A-Za-z0-9_.-]+', '_', value)
    safe = safe.strip('._') or 'test'
    digest = hashlib.sha1(value.encode('utf-8')).hexdigest()[:8]
    return f'{safe[:96]}_{digest}'


def set_sim_run_id(run_id: str) -> None:
    """Select the workspace for the current test (called by conftest)."""
    _SIM_RUN_ID.set(_sanitize_run_id(run_id))


def current_sim_run_id() -> str:
    run_id = _SIM_RUN_ID.get()
    if run_id is None:
        # Direct invocation outside pytest (e.g. a REPL or a helper script):
        # fall back to one private workspace per process.
        run_id = _sanitize_run_id(f'{os.getpid()}_adhoc_{uuid.uuid4().hex[:8]}')
        _SIM_RUN_ID.set(run_id)
    return run_id


def sim_run_dir() -> str:
    """Root of the current test's private tree (created on demand)."""
    path = os.path.join(REPO_ROOT, 'sims', 'runs', current_sim_run_id())
    os.makedirs(path, exist_ok=True)
    return path


def sim_sims_dir() -> str:
    """Working directory for compilers and simulation binaries."""
    path = os.path.join(sim_run_dir(), 'sims')
    os.makedirs(path, exist_ok=True)
    return path


def sim_logs_dir() -> str:
    path = os.path.join(sim_run_dir(), 'logs')
    os.makedirs(path, exist_ok=True)
    return path


def sim_log_path(name: str) -> str:
    """Return a log path inside the private workspace.

    *name* may be a bare filename or an old-style ``tests/logs/foo.log`` path;
    only the basename is used so logs never escape the workspace.
    """
    name = os.path.basename(name.replace('\\', '/')) or 'simulation.log'
    path = os.path.join(sim_logs_dir(), name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


def _copy_rtl_workspace() -> None:
    dst = os.path.join(sim_run_dir(), 'rtl')
    src = os.path.join(REPO_ROOT, 'rtl')
    if not os.path.isdir(dst):
        shutil.copytree(
            src, dst,
            ignore=shutil.ignore_patterns('qracc_params.svh', '__pycache__'),
        )
    # Seed a default parameter file so a test that does not call
    # write_parameter_definition_file still compiles with the same defaults
    # as the checkout's documented defaults.
    params = os.path.join(dst, 'qracc_params.svh')
    if not os.path.exists(params):
        defaults = os.path.join(dst, 'qracc_params_defaults.svh')
        if os.path.exists(defaults):
            shutil.copyfile(defaults, params)
        else:  # pragma: no cover - repository layout guard
            with open(params, 'w') as f:
                f.write('`ifndef PARAMETERS_FILE\n')
                f.write('`define PARAMETERS_FILE\n')
                f.write('`endif // PARAMETERS_FILE\n')


def sim_rtl_dir() -> str:
    """Private copy of ``rtl/`` used by the current test."""
    with _WORKSPACE_LOCK:
        _copy_rtl_workspace()
    return os.path.join(sim_run_dir(), 'rtl')


def sim_params_path() -> str:
    """Path of this test's private ``qracc_params.svh``."""
    return os.path.join(sim_rtl_dir(), 'qracc_params.svh')


def tb_relpath(tb_path: str) -> str | None:
    """Normalise *tb_path* to a path relative to the repository ``tb/`` dir.

    Accepts ``qracc_top``, ``qracc_top/tb_qracc_top.sv``, ``tb/qracc_top``,
    ``../tb/qracc_top/tb_qracc_top.sv`` and absolute paths below ``tb/``.
    Returns ``None`` when the path is not under the repository ``tb/`` tree.
    """
    raw = tb_path.replace('\\', '/')
    tb_root = os.path.join(REPO_ROOT, 'tb')

    if os.path.isabs(raw):
        try:
            rel = os.path.relpath(raw, tb_root)
        except ValueError:  # different drive on Windows
            return None
        if rel == '..' or rel.startswith('..' + os.sep) or os.path.isabs(rel):
            return None
        return rel.replace(os.sep, '/')

    for prefix in ('../tb/', 'tb/'):
        if raw.startswith(prefix):
            return raw[len(prefix):]

    # Bare block name or block-relative file (e.g. 'qracc_top').
    return raw


def _materialize_tb(rel: str) -> None:
    """Copy ``tb/<rel>`` (file or directory) into the private tree."""
    rel = rel.strip('/').replace('\\', '/')
    if not rel or rel == '.':
        return

    src = os.path.join(REPO_ROOT, 'tb', *rel.split('/'))
    dst = os.path.join(sim_run_dir(), 'tb', *rel.split('/'))

    with _WORKSPACE_LOCK:
        if os.path.isdir(src):
            if not os.path.isdir(dst):
                shutil.copytree(
                    src, dst,
                    ignore=shutil.ignore_patterns(
                        'inputs', 'outputs', '__pycache__'),
                )
            block_dir = dst
        elif os.path.isfile(src):
            block_dir = os.path.dirname(dst)
            os.makedirs(block_dir, exist_ok=True)
            if not os.path.isfile(dst):
                shutil.copy2(src, dst)
        else:
            # Unknown testbench: let the simulator produce its normal error.
            return

        # The testbenches use inputs/ and outputs/ whether or not the checked
        # out block ships them.
        os.makedirs(os.path.join(block_dir, 'inputs'), exist_ok=True)
        os.makedirs(os.path.join(block_dir, 'outputs'), exist_ok=True)


def ensure_tb_path(tb_path: str) -> str | None:
    """Materialise a testbench path and return its repository-relative form."""
    rel = tb_relpath(tb_path)
    if rel is None:
        return None
    _materialize_tb(rel)
    return rel


def sim_tb_dir(tb_path: str) -> str:
    """Private copy of a testbench block directory (e.g. ``qracc_top``)."""
    rel = ensure_tb_path(tb_path)
    if rel is None:
        raise ValueError(f'{tb_path!r} is not inside {os.path.join(REPO_ROOT, "tb")}')
    # Callers pass a block name; if they passed a file, return its directory.
    path = os.path.join(sim_run_dir(), 'tb', *rel.split('/'))
    if os.path.isfile(path):
        path = os.path.dirname(path)
    return path


def sim_inputs(tb_path: str) -> str:
    return os.path.join(sim_tb_dir(tb_path), 'inputs')


def sim_outputs(tb_path: str) -> str:
    return os.path.join(sim_tb_dir(tb_path), 'outputs')


def cleanup_sim_run(run_id: str | None = None) -> None:
    """Delete a private workspace (used after a passing test)."""
    run_id = run_id or current_sim_run_id()
    path = os.path.join(REPO_ROOT, 'sims', 'runs', run_id)
    shutil.rmtree(path, ignore_errors=True)
