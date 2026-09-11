"""Intent gates: is a facet band a tessellated cylinder, or a designed prism?

The three states a band must end in (n4 spec §1): REBUILT, KEPT+WARNED, KEPT+SILENT.
A wrong rebuild nobody is told about is strictly worse than no rebuild, so the
decisive assertions here are the ones that forbid a silent wrong rebuild.

Fixture note: `verbatim + no_unify` writes one planar face per TRIANGLE, so a
24-sided prism arrives as 48 faces. Any sagitta computed from a raw face count is
therefore 4x too small; the evidence must come from DISTINCT facet normals. The
prism/cylinder separation test below is what pins that down.
"""

import math

import pytest
import trimesh

from mesh2step.native import convert_native
from mesh2step.rebuild import find_bands, rebuild_cylinders


def _faceted(mesh, tmp_path, name):
    stl = tmp_path / f"{name}.stl"
    mesh.export(str(stl))
    step = tmp_path / f"{name}.step"
    convert_native(stl, step, engine="verbatim", no_unify=True)
    return step


def _sagitta(radius: float, sides: int) -> float:
    return radius * (1.0 - math.cos(math.pi / sides))


# --- class (a): designed prism vs tessellated cylinder -----------------------

@pytest.fixture(scope="module")
def prism_and_cylinder(tmp_path_factory):
    """One model, two bands, 105x apart in implied chord tolerance.

    A 24-gon of r=12.3 implies a sagitta of 0.105mm. A 200-facet cylinder of r=8
    implies 0.00099mm. One tessellator applies ONE chord tolerance to a whole
    model, so the coarse band cannot be a tessellation of anything -- it is the
    designed shape. Measured before this test existed: the rebuild took BOTH,
    moving the volume +0.81%, silently, under the webapp's 2% acceptance gate.
    """
    tmp = tmp_path_factory.mktemp("intent_a")
    prism = trimesh.creation.cylinder(radius=12.3, height=10, sections=24)
    prism.apply_translation([40, 0, 0])
    cyl = trimesh.creation.cylinder(radius=8.0, height=10, sections=200)
    both = trimesh.util.concatenate([prism, cyl])
    return _faceted(both, tmp, "prism_plus_cyl"), float(both.volume)


def test_a_designed_prism_is_never_silently_rebuilt(prism_and_cylinder, tmp_path):
    """The whole point of the exercise. +0.81% with no warning is the bug."""
    step, _mesh_volume = prism_and_cylinder
    res = rebuild_cylinders(step, tmp_path / "out.step")

    prism_volume = 0.5 * 24 * 12.3**2 * math.sin(2 * math.pi / 24) * 10.0
    circumscribed = math.pi * 12.3**2 * 10.0
    assert circumscribed > prism_volume  # the fixture is capable of showing the bug

    decisions = res["decisions"]
    prism_band = [d for d in decisions if abs(d["radius"] - 12.3) < 0.05]
    assert len(prism_band) == 1, decisions
    assert prism_band[0]["verdict"] != "rebuilt", prism_band[0]


def test_the_prism_keeps_the_volume_the_mesh_had(prism_and_cylinder, tmp_path):
    """Not rebuilding it is only half the contract: the volume must be the facets'."""
    step, mesh_volume = prism_and_cylinder
    res = rebuild_cylinders(step, tmp_path / "out.step")
    # the fine cylinder IS rebuilt, and that legitimately recovers its own sagitta;
    # what must not move is the prism's contribution.
    cyl_gain = math.pi * 8.0**2 * 10.0 - (0.5 * 200 * 8.0**2 * math.sin(2 * math.pi / 200) * 10.0)
    assert res["volume"] == pytest.approx(mesh_volume + cyl_gain, rel=1e-4), (
        f"volume {res['volume']:.4f} vs mesh {mesh_volume:.4f} (+cyl {cyl_gain:.4f})"
    )


def test_the_kept_prism_is_warned_about_with_its_numbers(prism_and_cylinder, tmp_path):
    """State 2 is KEPT FACETED, WARNED -- and the warning carries the evidence."""
    step, _ = prism_and_cylinder
    res = rebuild_cylinders(step, tmp_path / "out.step")
    warnings = res["warnings"]
    assert warnings, res
    text = " ".join(warnings)
    assert "24" in text, text          # the facet count
    assert "12.3" in text, text        # the radius
    for token in ("sagitta", "tolerance"):
        assert token in text.lower(), text


def test_the_tessellated_cylinder_beside_it_is_still_rebuilt(prism_and_cylinder, tmp_path):
    """Control against over-correction: the fine band must not become collateral."""
    step, _ = prism_and_cylinder
    res = rebuild_cylinders(step, tmp_path / "out.step")
    fine = [d for d in res["decisions"] if abs(d["radius"] - 8.0) < 0.05]
    assert len(fine) == 1, res["decisions"]
    assert fine[0]["verdict"] == "rebuilt", fine[0]


def test_the_evidence_reads_the_prism_sagitta_from_distinct_normals(prism_and_cylinder):
    """48 triangles, 24 sides. Counting faces gives 0.026mm; the truth is 0.105mm.

    This is the assertion that forbids implementing the evidence off a raw face
    count -- the separation would still 'work', but every number in the warning
    would be wrong by 4x.
    """
    from mesh2step.intent import band_evidence

    step, _ = prism_and_cylinder
    bands = find_bands(step)
    prism = [b for b in bands if abs(b.radius - 12.3) < 0.05]
    assert len(prism) == 1
    ev = band_evidence(prism[0], step)
    assert ev.sides == 24, ev
    assert ev.sagitta == pytest.approx(_sagitta(12.3, 24), rel=0.1), ev


# --- class (c): one bore vs two coaxial holes -------------------------------

def test_two_holes_three_tenths_apart_stay_two_cylinders(tmp_path):
    """Measured today: this yields FIVE bands. The walls are 0.3mm apart, which
    the old MAX_AXIAL_GAP_MM = 0.5 constant merges, and the fragmentation on top
    is its own defect. Two blind holes are two cylinders."""
    box = trimesh.creation.box((40, 20, 20))
    holes = []
    for sign in (-1.0, 1.0):
        d = trimesh.creation.cylinder(radius=2.5, height=19.85, sections=96)
        d.apply_transform(trimesh.transformations.rotation_matrix(math.pi / 2, [0, 1, 0]))
        d.apply_translation([sign * 10.075, 0, 0])
        holes.append(d)
    part = trimesh.boolean.difference([box, trimesh.util.concatenate(holes)])
    step = _faceted(part, tmp_path, "twoholes")

    bands = find_bands(step)
    assert len(bands) == 2, [(round(b.radius, 3), round(b.height, 3)) for b in bands]
    for b in bands:
        assert b.radius == pytest.approx(2.5, abs=0.01)


def test_a_through_bore_stays_one_cylinder(tmp_path):
    """Control for the test above: same radius, no wall in between."""
    box = trimesh.creation.box((40, 20, 20))
    drill = trimesh.creation.cylinder(radius=2.5, height=80, sections=96)
    drill.apply_transform(trimesh.transformations.rotation_matrix(math.pi / 2, [0, 1, 0]))
    part = trimesh.boolean.difference([box, drill])
    step = _faceted(part, tmp_path, "bore")

    bands = find_bands(step)
    assert len(bands) == 1, [(round(b.radius, 3), round(b.height, 3)) for b in bands]


# --- class (b): fillet vs rim ------------------------------------------------

def test_a_filleted_box_reports_no_lost_circles(tmp_path):
    """REGRESSION GUARD, not an F2P.

    Measured against the current detector: a genuine OCCT fillet on all 24 edges
    of a box, tessellated at 0.01mm, already yields 0 circles and 0 bands. Class
    (b) does not reproduce, so there is nothing here to fix -- but the intent work
    could easily start accepting these strips, and this is what would catch it.
    """
    from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.StlAPI import StlAPI_Writer
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    from mesh2step.canonize import find_circles

    box = BRepPrimAPI_MakeBox(20.0, 20.0, 20.0).Shape()
    fil = BRepFilletAPI_MakeFillet(box)
    ex = TopExp_Explorer(box, TopAbs_EDGE)
    while ex.More():
        fil.Add(3.0, TopoDS.Edge_s(ex.Current()))
        ex.Next()
    shape = fil.Shape()

    BRepMesh_IncrementalMesh(shape, 0.01, False, 0.5, True)
    stl = tmp_path / "fillet_box.stl"
    writer = StlAPI_Writer()
    writer.ASCIIMode = False
    writer.Write(shape, str(stl))

    step = tmp_path / "fillet_box.step"
    convert_native(stl, step, engine="verbatim", no_unify=True)

    assert find_circles(step) == []
    assert find_bands(step) == []

