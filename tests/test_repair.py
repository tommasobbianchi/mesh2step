import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import numpy as np
import trimesh
import pytest

from mesh2step.dedup import smart_tolerance
from mesh2step.io_mesh import load_mesh
from mesh2step.native import convert_native
from mesh2step.repair import REPAIR_LEVELS, repair_mesh


def _native_convert(stl_path, out_path, *, repair=None):
    """Repair (optionally) then convert through the native engine (verbatim, no unify)."""
    verts, tris = load_mesh(stl_path)
    rr = None
    if repair is not None:
        rr = repair_mesh(verts, tris, level=repair)
        verts, tris = rr.verts, rr.tris
    stl = out_path.with_suffix(".stl")
    trimesh.Trimesh(vertices=verts, faces=tris, process=False).export(str(stl))
    return convert_native(stl, out_path, engine="verbatim", no_unify=True), rr


def _is_solid(res) -> bool:
    return res["solids"] > 0 and res["openShells"] == 0


def _holed_cube_stl(tmp_path):
    m = trimesh.creation.box((10, 10, 10))
    faces = m.faces[1:]  # drop face 0
    m2 = trimesh.Trimesh(vertices=m.vertices, faces=faces, process=False)
    p = tmp_path / "holed_cube.stl"
    m2.export(str(p))
    return str(p)


def _duplicated_cube_stl(tmp_path):
    m = trimesh.creation.box((10, 10, 10))
    faces = np.vstack([m.faces, m.faces[:1]])
    m2 = trimesh.Trimesh(vertices=m.vertices, faces=faces, process=False)
    p = tmp_path / "duplicated_cube.stl"
    m2.export(str(p))
    return str(p)


class TestRepairModule:
    def test_repair_levels_const(self):
        assert REPAIR_LEVELS == ("weld", "fill", "solidify")

    def test_bad_repair_level_rejected(self):
        m = trimesh.creation.box((10, 10, 10))
        with pytest.raises(ValueError, match="repair level"):
            repair_mesh(m.vertices, m.faces, level="xxx")

    def test_weld_on_watertight_unchanged(self):
        m = trimesh.creation.box((10, 10, 10))
        rr = repair_mesh(m.vertices, m.faces, level="weld")
        assert rr.n_faces_before == 12
        assert rr.n_faces_after == 12
        assert rr.n_duplicate_faces_removed == 0
        assert rr.watertight_after is True
        assert rr.holes_filled is False


class TestRepairConvert:
    def test_open_mesh_not_solid_without_repair(self, tmp_path):
        stl = _holed_cube_stl(tmp_path)
        out = tmp_path / "out.step"
        res, _ = _native_convert(stl, out)
        assert _is_solid(res) is False

    def test_weld_alone_insufficient_for_hole(self, tmp_path):
        stl = _holed_cube_stl(tmp_path)
        out = tmp_path / "out.step"
        res, _ = _native_convert(stl, out, repair="weld")
        assert _is_solid(res) is False

    def test_fill_closes_hole_to_solid(self, tmp_path):
        stl = _holed_cube_stl(tmp_path)
        out = tmp_path / "out.step"
        res, _ = _native_convert(stl, out, repair="fill")
        assert _is_solid(res) is True
        assert abs(res["stepVolumeMM3"] - 1000.0) < 1e-2

    def test_duplicate_faces_removed_by_weld(self, tmp_path):
        stl = _duplicated_cube_stl(tmp_path)
        out = tmp_path / "out.step"
        res, rr = _native_convert(stl, out, repair="weld")
        assert rr.n_duplicate_faces_removed == 1
        assert _is_solid(res) is True


class TestSmartTolerance:
    def test_smart_tolerance_scales_with_size(self):
        m_small = trimesh.creation.box((1, 1, 1))
        m_large = trimesh.creation.box((1000, 1000, 1000))
        tol_small = smart_tolerance(m_small.vertices)
        tol_large = smart_tolerance(m_large.vertices)
        assert 0.0003 < tol_small < 0.002
        assert tol_large > tol_small * 100
        assert tol_large < tol_small * 2000

    def test_solidify_makes_nonmanifold_solid(self, tmp_path):
        pytest.importorskip("pymeshfix")
        m = trimesh.creation.box((10, 10, 10))
        faces = m.faces.copy()
        faces = faces[3:]  # remove 3 faces to create a large hole
        flipped = m.faces[0:1].copy()
        flipped[:, [0, 1]] = flipped[:, [1, 0]]  # flip winding of one face
        faces = np.vstack([faces, flipped])
        m2 = trimesh.Trimesh(vertices=m.vertices.copy(), faces=faces, process=False)
        stl = tmp_path / "broken.stl"
        m2.export(str(stl))
        out = tmp_path / "out.step"
        res, _ = _native_convert(str(stl), out, repair="solidify")
        assert _is_solid(res) is True

    def test_subunit_box_converts_fully(self, tmp_path):
        m = trimesh.creation.box((1, 1, 1))
        stl = tmp_path / "box1.stl"
        m.export(str(stl))
        out = tmp_path / "out.step"
        res, _ = _native_convert(str(stl), out)
        assert _is_solid(res) is True
        assert res["facesBeforeUnify"] == 12
