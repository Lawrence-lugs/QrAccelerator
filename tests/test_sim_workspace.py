"""Regression coverage for isolated public and proprietary RTL workspaces."""

from pathlib import Path
import os

import pytest

from tests import sim_workspace


@pytest.mark.parametrize("macro_available", [False, True])
def test_optional_sram_symlink(tmp_path, monkeypatch, macro_available):
    rtl = tmp_path / "rtl"
    macro_dir = rtl / "activation_buffer"
    macro_dir.mkdir(parents=True)
    (rtl / "qracc_params_defaults.svh").write_text("// defaults\n")
    (rtl / "seq_acc.sv").write_text("// ordinary RTL\n")
    (rtl / "qracc_params.svh").write_text("// stale params\n")

    target = tmp_path / "local_sram_model.sv"
    if macro_available:
        target.write_text("// local model\n")
    macro = macro_dir / "sram_32bank_8b.sv"
    try:
        macro.symlink_to(target)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"Symlink creation unavailable: {exc}")

    monkeypatch.setattr(sim_workspace, "REPO_ROOT", str(tmp_path))
    monkeypatch.setattr(sim_workspace, "_SIM_RUN_ID", sim_workspace.contextvars.ContextVar("test_run", default=None))
    sim_workspace.set_sim_run_id("optional_sram")
    copied = Path(sim_workspace.sim_rtl_dir())
    assert (copied / "seq_acc.sv").read_text() == "// ordinary RTL\n"
    assert (copied / "qracc_params.svh").read_text() == "// defaults\n"
    copied_macro = copied / "activation_buffer" / macro.name
    if macro_available:
        assert copied_macro.read_text() == "// local model\n"
        assert not copied_macro.is_symlink()
    else:
        assert not os.path.lexists(copied_macro)
    assert macro.is_symlink()
