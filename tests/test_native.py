import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from mesh2step.native import convert_native, native_available, native_binary

CORPUS = Path(__file__).resolve().parent / "data" / "corpus"


def _run_cli(args):
    return subprocess.run(
        [sys.executable, "-m", "mesh2step.cli", *args],
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_native_available_on_this_host():
    assert native_available() is True
    binary = native_binary()
    assert binary is not None
    assert binary.exists()


def test_convert_native_verbatim_cube(tmp_path):
    out = tmp_path / "cube.step"
    res = convert_native(CORPUS / "cube.stl", out, engine="verbatim")
    assert res["exit_code"] == 0
    assert res["solids"] == 1
    assert out.read_bytes().startswith(b"ISO-10303-21")


def test_convert_native_trueform_nonprismatic_exit_2(tmp_path):
    out = tmp_path / "nonprismatic.step"
    res = convert_native(CORPUS / "nonprismatic-control.stl", out, engine="trueform")
    assert res["exit_code"] == 2
    assert res["warnings"]
    assert out.read_bytes().startswith(b"ISO-10303-21")


def test_cli_trueform_emits_result_and_solids(tmp_path):
    out = tmp_path / "cube.step"
    proc = _run_cli([str(CORPUS / "cube.stl"), "-o", str(out), "--engine", "trueform", "--quiet"])
    assert proc.returncode == 0, proc.stderr
    lines = proc.stdout.strip().splitlines()
    assert lines[-1].startswith("RESULT ")
    payload = json.loads(lines[-1][len("RESULT ") :])
    assert payload["solids"] == 1


def test_cli_faceted_writes_iso_step(tmp_path):
    out = tmp_path / "cube.step"
    proc = _run_cli([str(CORPUS / "cube.stl"), "-o", str(out), "--engine", "verbatim", "--quiet"])
    assert proc.returncode == 0, proc.stderr
    assert out.read_bytes().startswith(b"ISO-10303-21")


def test_import_does_not_pull_refit():
    import mesh2step  # noqa: F401

    with pytest.raises(ImportError):
        importlib.import_module("mesh2step.refit")
