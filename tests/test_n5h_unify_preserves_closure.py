"""n5h: the second (smooth-flat) unify pass must never open a closed shell.

Measured on L08_T_bracket_recon (884 triangles, inside the 500-1200 band that gates the
second unify): the first unify leaves 821 faces and a closed shell; the smooth-flat pass
merges down to 440 faces and leaves 4 free edges bounding a quadrilateral hole where input
triangles 727 and 730 used to be. The mesh is closed, so the output must be closed too.
"""
import os
import subprocess

import pytest

from conftest import deployed_engine

MESH = "/tmp/awk/cadbench/L08_T_bracket_recon_normal.stl"


def _free_edges(step_path):
    from OCP.BRep import BRep_Tool
    from OCP.STEPControl import STEPControl_Reader
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE
    from OCP.TopExp import TopExp
    from OCP.TopoDS import TopoDS
    from OCP.TopTools import TopTools_IndexedDataMapOfShapeListOfShape

    reader = STEPControl_Reader()
    reader.ReadFile(str(step_path))
    reader.TransferRoots()
    anc = TopTools_IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(reader.OneShape(), TopAbs_EDGE, TopAbs_FACE, anc)
    return sum(
        1
        for i in range(1, anc.Extent() + 1)
        if not BRep_Tool.Degenerated_s(TopoDS.Edge_s(anc.FindKey(i)))
        and anc.FindFromIndex(i).Extent() == 1
    )


@pytest.mark.skipif(not os.path.exists(MESH), reason="corpus fixture absent")
def test_second_unify_never_opens_a_closed_shell(tmp_path):
    out = tmp_path / "l08.step"
    subprocess.run(
        [deployed_engine(), MESH, "-o", str(out), "--engine", "trueform"],
        check=False,
        capture_output=True,
        timeout=400,
    )
    assert out.exists(), "engine produced no output"
    assert _free_edges(out) == 0, "closed mesh produced an open shell"
