"""Feature builds replace engine output only as the mesh's shape, backed by its quad cylinders."""
import trimesh
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer

from mesh2step.feature import acceptable, measure, native_payload, support


def _box_step(path, x, y, z):
    w = STEPControl_Writer()
    w.Transfer(BRepPrimAPI_MakeBox(x, y, z).Shape(), STEPControl_AsIs)
    w.Write(str(path))


def _box_tri(x, y, z):
    m = trimesh.creation.box(extents=(x, y, z))
    m.apply_translation((x / 2, y / 2, z / 2))
    return m.vertices[m.faces]


def test_matching_build_is_accepted(tmp_path):
    _box_step(tmp_path / "b.step", 40, 20, 10)
    m = measure(tmp_path / "b.step", _box_tri(40, 20, 10))
    assert acceptable(m), m


def test_wrong_volume_is_refused(tmp_path):
    _box_step(tmp_path / "b.step", 40, 20, 11)  # +10% volume
    assert not acceptable(measure(tmp_path / "b.step", _box_tri(40, 20, 10)))


def test_right_volume_wrong_place_is_refused(tmp_path):
    _box_step(tmp_path / "b.step", 20, 40, 10)  # same volume, rotated footprint
    assert not acceptable(measure(tmp_path / "b.step", _box_tri(40, 20, 10)))


def test_support_counts_cylinders_the_mesh_shows():
    assert support([10.0, 10.02, 4.0, 2.5], [9.98, 4.01]) == 0.75
    assert support([], []) == 1.0


def test_payload_carries_the_built_counts_the_webapp_renders():
    # webapp _native_stats reads smoothBuilt*; without them a served feature build shows no cylinders
    p = native_payload({"volume": 1.0, "mesh_volume": 1.0, "dv_pct": 0.0, "faces": 9, "planes": 4,
                        "cylinders": 5, "method": "extrude-z", "support": 1.0, "dist_p95": 0.0},
                       "in.stl", "out.step", 1.0)
    assert (p["smoothBuiltPlanes"], p["smoothBuiltCylinders"]) == (4, 5)
    assert (p["smoothPlanes"], p["smoothCylinders"]) == (4, 5)
