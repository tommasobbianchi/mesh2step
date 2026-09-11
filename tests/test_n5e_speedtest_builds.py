"""F2P for the curve-choice chapter: SpeedTestStructure must build analytic faces.

Red on the production baseline v1.1.0-n5h: the component reverts wholesale
(smoothBuiltPlanes = 0, smoothBuiltCylinders = 0, smoothRevertedComponents = 1), so the
model contributes 0 of its 246 truth cylinders, 144 of which are inside the seed band.

Two levels, deliberately: the first is the minimal statement that the revert stopped, the
second is the chapter's stated target. The first going green while the second stays red is a
real intermediate state and the suite should be able to say so.
"""
import json
import os
import subprocess

import pytest
from conftest import deployed_engine

_NO_RESULT = "engine emitted no RESULT line"
MESH = "/tmp/awk/cadbench/SpeedTestStructure_coarse.stl"
MESH_NORMAL = "/tmp/awk/cadbench/SpeedTestStructure_normal.stl"


def _result(mesh, out):
    proc = subprocess.run(
        [deployed_engine(), str(mesh), "-o", str(out), "--engine", "trueform"],
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
    )
    for line in proc.stdout.splitlines():
        if line.startswith("RESULT "):
            return json.loads(line[7:])
    raise AssertionError(_NO_RESULT)


@pytest.mark.skipif(not os.path.exists(MESH), reason="corpus fixture absent")
def test_the_component_stops_reverting(tmp_path):
    res = _result(MESH, tmp_path / "st.step")
    built = res.get("smoothBuiltPlanes", 0) + res.get("smoothBuiltCylinders", 0)
    assert built > 0, "SpeedTestStructure still builds no analytic face at all"


@pytest.mark.skipif(not os.path.exists(MESH_NORMAL), reason="corpus fixture absent")
def test_in_band_cylinders_reach_the_target(tmp_path):
    res = _result(MESH_NORMAL, tmp_path / "stn.step")
    assert res.get("smoothBuiltCylinders", 0) >= 144, (
        "target is the 144 in-band truth cylinders of this model"
    )
