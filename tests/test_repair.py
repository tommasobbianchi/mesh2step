import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import numpy as np
import trimesh
import pytest

from mesh2step.convert import convert_file
from mesh2step.repair import REPAIR_LEVELS, repair_mesh


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
        assert REPAIR_LEVELS == ("weld", "fill")

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
        stats = convert_file(stl, out, tolerance=0.01)
        assert stats.is_solid is False

    def test_weld_alone_insufficient_for_hole(self, tmp_path):
        stl = _holed_cube_stl(tmp_path)
        out = tmp_path / "out.step"
        stats = convert_file(stl, out, tolerance=0.01, repair="weld")
        assert stats.is_solid is False

    def test_fill_closes_hole_to_solid(self, tmp_path):
        stl = _holed_cube_stl(tmp_path)
        out = tmp_path / "out.step"
        stats = convert_file(stl, out, tolerance=0.01, repair="fill")
        assert stats.is_solid is True
        assert abs(stats.volume - 1000.0) < 1e-2

    def test_duplicate_faces_removed_by_weld(self, tmp_path):
        stl = _duplicated_cube_stl(tmp_path)
        out = tmp_path / "out.step"
        stats = convert_file(stl, out, tolerance=0.01, repair="weld")
        assert stats.n_nonmanifold_edges == 0
        assert stats.is_solid is True
