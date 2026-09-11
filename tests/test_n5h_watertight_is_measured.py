"""n5h: the engine's watertight flag is measured on the written shape, not asserted.

Before this change `watertight` described the INPUT mesh and `openShells` was counted before
the coplanar merge, so L08_T_bracket_recon reported watertight=true, openShells=0 for a file
that carried 4 free edges. The Python audit reads this flag, so a lying flag is a state-2
silent-wrong-rebuild that the audit cannot see.
"""
import os
import subprocess

import pytest

from conftest import deployed_engine
from mesh2step.result import ParityResult

OPEN_STL = """solid open
 facet normal 0 0 1
  outer loop
   vertex 0 0 0
   vertex 10 0 0
   vertex 0 10 0
  endloop
 endfacet
 facet normal 0 0 1
  outer loop
   vertex 10 0 0
   vertex 10 10 0
   vertex 0 10 0
  endloop
 endfacet
endsolid open
"""

CLOSED = "/tmp/awk/cadbench/L08_T_bracket_recon_normal.stl"
_NO_RESULT = "engine emitted no RESULT line"


def _run(mesh, out):
    proc = subprocess.run(
        [deployed_engine(), str(mesh), "-o", str(out), "--engine", "trueform"],
        capture_output=True,
        text=True,
        timeout=400,
        check=False,
    )
    for line in proc.stdout.splitlines():
        if line.startswith("RESULT "):
            import json

            return json.loads(line[7:])
    raise AssertionError(_NO_RESULT)


def test_flag_reads_false_on_an_open_shape(tmp_path):
    """A flag that has never been observed false is not a measurement."""
    mesh = tmp_path / "open.stl"
    mesh.write_text(OPEN_STL)
    res = _run(mesh, tmp_path / "open.step")
    assert res["freeEdges"] == 4          # a quad boundary
    assert res["watertight"] is False
    assert res["openShells"] == 1


@pytest.mark.skipif(not os.path.exists(CLOSED), reason="corpus fixture absent")
def test_flag_agrees_with_the_written_shape(tmp_path):
    res = _run(CLOSED, tmp_path / "l08.step")
    assert res["watertight"] is (res["freeEdges"] == 0)


def test_result_carries_free_edges():
    r = ParityResult.from_native({"ok": True, "freeEdges": 7, "watertight": False})
    assert r.free_edges == 7
    assert r.to_dict()["freeEdges"] == 7
