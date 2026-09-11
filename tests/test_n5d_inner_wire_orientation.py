"""n5d: a planar face's inner wires must all be oriented consistently.

Measured mechanism (n4 report §21): the plate builder decided each hole loop's
orientation from that loop's own collapsed-circle properties, so two holes on one plate
could land on opposite orientations. BRepCheck then reports BadOrientationOfSubshape on
the face, the cascade ladder cannot explode the plate (RULE 3.2/S03 forbids exploding a
plate that touches a seamed hole), and RULE 1.4 discards the whole component -- 20 built
faces lost to 2 bad ones on L06_adapter_plate.

Engine is the deployed one (MESH2STEP_NATIVE overrides); red against the frozen reference
and the fixed fork build (must pass).
"""

import json
import pathlib
import subprocess

import numpy as np
import pytest
import trimesh
from conftest import deployed_engine

ENGINE = deployed_engine()


def _convert(mesh, tmp_path, name):
    stl = tmp_path / f"{name}.stl"
    mesh.export(str(stl))
    step = tmp_path / f"{name}.step"
    p = subprocess.run([ENGINE, str(stl), "-o", str(step), "--engine", "trueform"],
                       capture_output=True, text=True, timeout=900)
    res = [x for x in p.stdout.splitlines() if x.startswith("RESULT")]
    assert res, p.stdout[-2000:]
    return step, json.loads(res[-1][7:])


def _solid_health(step: pathlib.Path):
    """(closed, brepcheck_valid, volume) of the written STEP."""
    from OCP.BRep import BRep_Tool
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from OCP.STEPControl import STEPControl_Reader
    from OCP.TopAbs import TopAbs_SHELL
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    r = STEPControl_Reader()
    assert r.ReadFile(str(step)) == 1
    r.TransferRoots()
    shape = r.OneShape()
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    closed = True
    ex = TopExp_Explorer(shape, TopAbs_SHELL)
    while ex.More():
        if not BRep_Tool.IsClosed_s(TopoDS.Shell_s(ex.Current())):
            closed = False
            break
        ex.Next()
    return closed, bool(BRepCheck_Analyzer(shape).IsValid()), float(props.Mass())


def _plate_with_holes(radii, thickness=6.0, plate=44.0, sections=None):
    """A plate drilled with holes of the given radii, tessellated per hole.

    Different section counts make the rims collapse differently -- one may reduce to a
    single full-circle edge and another may not, which is exactly the case the old
    four-condition guard treated inconsistently.
    """
    body = trimesh.creation.box((plate, plate, thickness))
    xs = np.linspace(-plate / 3, plate / 3, len(radii))
    drills = []
    for r, x, n in zip(radii, xs, sections or [96] * len(radii), strict=True):
        d = trimesh.creation.cylinder(radius=r, height=thickness * 4, sections=n)
        d.apply_translation([float(x), 0.0, 0.0])
        drills.append(d)
    return trimesh.boolean.difference([body, trimesh.util.concatenate(drills)])


def test_two_holes_whose_rims_collapse_differently(tmp_path):
    """(1) One rim reduces to a single full-circle edge, the other does not."""
    mesh = _plate_with_holes([5.0, 2.0], sections=[96, 40])
    step, stats = _convert(mesh, tmp_path, "two_holes")

    assert stats.get("smoothCylinders", 0) > 0, stats.get("warnings")
    closed, valid, vol = _solid_health(step)
    assert closed, "shell is not closed"
    assert valid, "BRepCheck rejects the solid"
    assert vol > 0, f"volume {vol} is not positive"


def test_many_holes_of_alternating_circle_direction(tmp_path):
    """(2) N >= 3 holes; their natural circle directions need not agree."""
    mesh = _plate_with_holes([4.0, 2.5, 4.0, 2.5], sections=[96, 48, 64, 32])
    step, stats = _convert(mesh, tmp_path, "many_holes")

    assert stats.get("smoothCylinders", 0) >= 3, stats.get("warnings")
    closed, valid, vol = _solid_health(step)
    assert closed and valid and vol > 0, (closed, valid, vol)


@pytest.mark.skipif(not pathlib.Path("/tmp/awk/cadbench/L06_adapter_plate_normal.stl").exists(),
                    reason="corpus not present")
def test_the_corpus_model_that_lost_twenty_faces_to_two(tmp_path):
    """P29's subject: 20 built faces discarded because 2 plates were mis-oriented."""
    stl = pathlib.Path("/tmp/awk/cadbench/L06_adapter_plate_normal.stl")
    step = tmp_path / "adapter.step"
    p = subprocess.run([ENGINE, str(stl), "-o", str(step), "--engine", "trueform"],
                       capture_output=True, text=True, timeout=900)
    d = json.loads([x for x in p.stdout.splitlines() if x.startswith("RESULT")][-1][7:])
    assert d.get("smoothRevertedComponents", 0) == 0, d.get("warnings")
    assert d.get("smoothCylinders", 0) > 0, d
