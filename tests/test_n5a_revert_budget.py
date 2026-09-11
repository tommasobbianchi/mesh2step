"""n5a: the revert budget must AUTHORISE a consistent band's expected change.

P7 measured the defect: `budget = max(1e-4*refVol, 3*dVolPredAbs)` against a correct
rebuild whose volume change is 27.8x that on L06_adapter_plate and 22.2x on
L04_cyl_bottom_chamf. The guard discards correct rebuilds for moving the volume by
exactly what geometry requires.

The fix must AUTHORISE, not ABSORB: only bands consistent with the component's own
tessellation fingerprint earn an allowance. A designed octagon (theta 45 deg, ratio 106)
earns none -- otherwise a wider budget would let projects-ccf through silently and we
would have traded one silent wrong rebuild for another.

Engine is the deployed one (MESH2STEP_NATIVE overrides), so the same tests run against the
frozen binary (must fail) and the n5a fork build (must pass).
"""

import json
import math
import pathlib
import subprocess

import pytest
from conftest import deployed_engine

CORPUS = pathlib.Path("/tmp/awk/cadbench")
ENGINE = deployed_engine()


def _run(stl: pathlib.Path, out: pathlib.Path) -> dict:
    p = subprocess.run([ENGINE, str(stl), "-o", str(out), "--engine", "trueform"],
                       capture_output=True, text=True, timeout=900)
    res = [x for x in p.stdout.splitlines() if x.startswith("RESULT")]
    assert res, p.stdout[-2000:]
    return json.loads(res[-1][7:])


@pytest.mark.skipif(not (CORPUS / "L06_adapter_plate_normal.stl").exists(),
                    reason="corpus not present")
def test_a_consistent_coarse_hole_set_stops_reverting(tmp_path):
    """14 coarse-but-consistent holes, zero construction warnings, reverted anyway.

    Frozen engine (measured): reverted=1, smoothCylinders=0, and the output volume
    equals the mesh volume to 9 decimals -- the rebuild was computed and thrown away.
    Its predicted change is 79.38 mm3 against a budget of 2.86 mm3.
    """
    d = _run(CORPUS / "L06_adapter_plate_normal.stl", tmp_path / "plate.step")
    assert d.get("smoothRevertedComponents", 0) == 0, d.get("warnings")
    assert d.get("smoothCylinders", 0) > 0, d


@pytest.mark.skipif(not (CORPUS / "L04_cyl_bottom_chamf_normal.stl").exists(),
                    reason="corpus not present")
def test_the_second_budget_only_casualty_also_stops_reverting(tmp_path):
    """L04_cyl_bottom_chamf: predicted 16.81 mm3 against a 0.76 mm3 budget (22.2x).

    This one ALSO emits seamed360 warnings, so if it still reverts after n5a the cause
    is n5c's mixed boundary, not the budget -- record which, do not silently pass.
    """
    d = _run(CORPUS / "L04_cyl_bottom_chamf_normal.stl", tmp_path / "chamf.step")
    assert d.get("smoothRevertedComponents", 0) == 0, d.get("warnings")


def test_a_designed_octagon_earns_no_allowance(tmp_path):
    """The constraint that keeps n5a from re-opening projects-ccf.

    A lone 8-gon is 45 deg per facet. It must not be quietly absorbed by a wider
    budget: the volume it produces must still be the circumscribed cylinder's
    (x1.1107), i.e. n5a changes nothing about whether it is accepted -- and the
    mesh-side audit must still flag it.
    """
    import trimesh

    from mesh2step.intent import audit_engine_cylinders

    mesh = trimesh.creation.cylinder(radius=20.0, height=20.0, sections=8)
    stl = tmp_path / "octagon.stl"
    mesh.export(str(stl))
    step = tmp_path / "octagon.step"
    d = _run(stl, step)

    mesh_v = d.get("meshVolumeMM3")
    step_v = d.get("stepVolumeMM3")
    assert mesh_v and step_v
    ratio = step_v / mesh_v
    expected = 2 * math.pi / (8 * math.sin(math.radians(45)))
    assert ratio == pytest.approx(expected, rel=1e-4), (ratio, expected)

    flagged = [r for r in audit_engine_cylinders(stl, step) if r.flagged]
    assert flagged, "the octagon must never pass unflagged"
    assert flagged[0].sides == 8
