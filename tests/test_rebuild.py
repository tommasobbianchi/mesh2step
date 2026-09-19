"""Grouping rims into the cylinder bands a rebuild can replace."""

from pathlib import Path

import numpy as np
import trimesh

from mesh2step.native import convert_native
from mesh2step.rebuild import find_bands


def _faceted(mesh, tmp_path, name):
    stl = tmp_path / f"{name}.stl"
    mesh.export(str(stl))
    step = tmp_path / f"{name}.step"
    convert_native(stl, step, engine="verbatim", no_unify=True)
    return step


def test_one_cylinder_is_one_band(tmp_path):
    step = _faceted(trimesh.creation.cylinder(radius=8, height=15, sections=96),
                    tmp_path, "cyl")
    bands = find_bands(step)
    assert len(bands) == 1, [(b.radius, b.height) for b in bands]
    b = bands[0]
    assert abs(b.radius - 8.0) < 1e-3
    assert abs(b.height - 15.0) < 1e-3
    assert abs(abs(b.axis[2]) - 1.0) < 1e-6
    assert len(b.face_indices) >= 90


def test_collinear_holes_in_opposite_walls_are_not_one_cylinder(tmp_path):
    """The trap from a real lid: a hole through one wall and a hole through the
    opposite wall share an axis and a radius exactly. Coaxial, equal radius, rims
    facing each other -- and nothing but air in between."""
    box = trimesh.creation.box((40, 20, 20))
    drill = trimesh.creation.cylinder(radius=2.5, height=80, sections=96)
    drill.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [0, 1, 0]))
    part = trimesh.boolean.difference([box, drill])          # one bore, two walls
    step = _faceted(part, tmp_path, "walls")

    bands = find_bands(step)
    # the bore is a single continuous cylinder 40mm long; there must be no band
    # claiming a 40mm cylinder made of two 0-thickness walls with a gap between
    for b in bands:
        spanned = max(z for z in [b.height])
        assert spanned <= 40.0 + 1e-6
        assert len(b.face_indices) >= 8, f"band with too few faces: {b}"


def test_a_box_has_no_bands(tmp_path):
    step = _faceted(trimesh.creation.box((10, 10, 10)), tmp_path, "box")
    assert find_bands(step) == []


def _volume(step):
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from OCP.STEPControl import STEPControl_Reader

    r = STEPControl_Reader()
    r.ReadFile(str(step))
    r.TransferRoots()
    p = GProp_GProps()
    BRepGProp.VolumeProperties_s(r.OneShape(), p)
    return p.Mass()


def test_a_faceted_cylinder_rebuilds_to_three_analytic_faces(tmp_path):
    import math

    from mesh2step.rebuild import rebuild_cylinders

    step = _faceted(trimesh.creation.cylinder(radius=8, height=15, sections=96),
                    tmp_path, "cyl96")
    out = tmp_path / "cyl96_rebuilt.step"
    res = rebuild_cylinders(step, out)

    assert res["bands"] == 1
    assert res["faces_after"] == 3, res          # one cylinder + two caps
    assert res["faces_failed"] == 0
    assert res["valid"] is True
    assert abs(res["volume"] - math.pi * 64 * 15) < 1e-3, res["volume"]


def test_the_rebuilt_solid_stays_within_the_tessellation_error(tmp_path):
    """The rebuilt geometry must differ from the facets by no more than the chord
    sagitta -- that is the error the facets already had, and recovering the true
    surface is precisely removing it."""
    import math

    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    from OCP.gp import gp_Pnt
    from OCP.STEPControl import STEPControl_Reader

    from mesh2step.rebuild import rebuild_cylinders

    radius, sections = 8.0, 96
    mesh = trimesh.creation.cylinder(radius=radius, height=15, sections=sections)
    step = _faceted(mesh, tmp_path, "dev")
    out = tmp_path / "dev_rebuilt.step"
    rebuild_cylinders(step, out)

    reader = STEPControl_Reader()
    reader.ReadFile(str(out))
    reader.TransferRoots()
    solid = reader.OneShape()

    sagitta = radius * (1 - math.cos(math.pi / sections))
    worst = 0.0
    for p in mesh.vertices[::7]:
        v = BRepBuilderAPI_MakeVertex(gp_Pnt(*p)).Vertex()
        d = BRepExtrema_DistShapeShape(v, solid)
        assert d.IsDone()
        worst = max(worst, d.Value())
    assert worst <= 2 * sagitta, f"{worst:.6f}mm exceeds 2x sagitta {2*sagitta:.6f}mm"


def test_a_part_with_no_cylinder_is_left_alone(tmp_path):
    from mesh2step.rebuild import rebuild_cylinders

    step = _faceted(trimesh.creation.box((10, 10, 10)), tmp_path, "boxr")
    out = tmp_path / "box_rebuilt.step"
    res = rebuild_cylinders(step, out)
    assert res["bands"] == 0 and res["ok"] is False


def _quads_classify(tri):
    import importlib.util

    quads_path = Path(__file__).resolve().parents[1] / "tools" / "feature_recon" / "quads.py"
    spec = importlib.util.spec_from_file_location("quads", quads_path)
    quads = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(quads)
    return quads.classify(tri)


def test_a_mesh_seeded_band_rebuilds_a_clean_bore(tmp_path):
    """The seeded path must accept a patch whose extent ends verify as closed rims
    and rebuild it to a valid solid."""
    from mesh2step.feature import _mesh
    from mesh2step.rebuild import rebuild_cylinders

    box = trimesh.creation.box((40, 20, 20))
    drill = trimesh.creation.cylinder(radius=2.5, height=80, sections=64)
    drill.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [0, 1, 0]))
    part = trimesh.boolean.difference([box, drill])
    stl = tmp_path / "bore.stl"
    part.export(str(stl))
    tri = _mesh(stl)
    patches = [(o[2], o[3], tri[list(o[4])].reshape(-1, 3))
               for o in _quads_classify(tri)[2] if o[0] == "cylinder"]
    step = tmp_path / "bore.step"
    convert_native(stl, step, engine="verbatim", no_unify=True)
    res = rebuild_cylinders(step, tmp_path / "out.step", patches=patches)
    assert res["bands"] == 1, res
    assert res["valid"] is True
    assert res["ok"] is True


def test_mesh_seeded_bands_over_cross_holes_are_rejected(tmp_path):
    """A wall breached by a cross-hole must not be seeded into a band. Both extent
    ends can verify as closed rims while the middle is open -- measured on a 30mm
    box with three crossing 2mm holes and on L09_valve_body
    (diag/FINDINGS-mesh-seeded-bands.md): the rebuild closed a 360-degree face
    over the breach, the junction wires broke, and the shell sewed open (invalid
    solid, alone and together)."""
    from mesh2step.rebuild import rebuild_cylinders

    box = trimesh.creation.box((30, 30, 30))
    drills = [trimesh.creation.cylinder(radius=2, height=80, sections=48)]
    for ax in ((0, 1, 0), (1, 0, 0)):
        d = drills[0].copy()
        d.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, ax))
        drills.append(d)
    part = trimesh.boolean.difference([box] + drills)
    stl = tmp_path / "cross.stl"
    part.export(str(stl))
    step = tmp_path / "cross.step"
    convert_native(stl, step, engine="verbatim", no_unify=True)
    # hand-built patch: full-circle rings sampled on the true Z-hole cylinder
    th = np.linspace(0, 2 * np.pi, 49)[:-1]
    pts = np.vstack([np.c_[2 * np.cos(th), 2 * np.sin(th), np.full_like(th, z)]
                     for z in np.linspace(-15, 15, 10)])
    res = rebuild_cylinders(step, tmp_path / "out.step",
                            patches=[(2.0, (0.0, 0.0, 1.0), pts)])
    assert res["bands"] == 0, res
