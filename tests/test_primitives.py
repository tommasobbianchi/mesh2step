import trimesh

from conftest import read_step_volume
from mesh2step import convert_file


def _primitives():
    return {
        "box": trimesh.creation.box(extents=(10, 10, 10)),
        "cylinder": trimesh.creation.cylinder(radius=4, height=10, sections=48),
        "icosphere": trimesh.creation.icosphere(subdivisions=3, radius=5),
        "torus": trimesh.creation.torus(major_radius=8, minor_radius=2),
    }


PRIMITIVES = _primitives()


def _convert(name, tmp_stl, tmp_step, **kwargs):
    mesh = PRIMITIVES[name]
    stl_path = tmp_stl(mesh, f"{name}.stl")
    return mesh, convert_file(stl_path, tmp_step, **kwargs)


class TestFacetedFidelity:
    """Faceted mode: no surface fitting, no primitive recognition -- one face per
    surviving triangle, exact geometry."""

    def test_face_count_equals_triangle_count(self, tmp_stl, tmp_step):
        for name in PRIMITIVES:
            mesh, stats = _convert(name, tmp_stl, tmp_step)
            assert stats.error is None, f"{name}: {stats.error}"
            assert stats.n_degenerate_collapsed == 0, name
            assert stats.n_degenerate_zero_area == 0, name
            assert stats.n_faces_built == stats.n_kept_tris == len(mesh.faces), name

    def test_watertight_input_yields_closed_solid(self, tmp_stl, tmp_step):
        for name in PRIMITIVES:
            mesh, stats = _convert(name, tmp_stl, tmp_step)
            assert mesh.is_watertight, f"fixture {name} is not watertight, test invalid"
            assert stats.watertight is True, name
            assert stats.is_solid is True, name
            assert stats.n_boundary_edges == 0, name
            assert stats.n_nonmanifold_edges == 0, name

    def test_round_trip_volume_within_tolerance(self, tmp_stl, tmp_step):
        for name in PRIMITIVES:
            mesh, stats = _convert(name, tmp_stl, tmp_step)
            written_volume = read_step_volume(tmp_step)
            rel_err = abs(written_volume - mesh.volume) / mesh.volume
            assert rel_err < 1e-4, f"{name}: mesh volume={mesh.volume} step volume={written_volume}"
            # internal stats must also agree with what actually landed on disk
            assert abs(stats.volume - written_volume) / written_volume < 1e-9, name


class TestDegenerateHandling:
    def test_collapsed_triangle_is_rejected(self, tmp_stl, tmp_step):
        # two vertices within tolerance of each other -> quantizes to the same index
        mesh = PRIMITIVES["box"].copy()
        v = mesh.vertices
        degenerate_tri = [list(v[0]), list(v[1]), [v[0][0] + 1e-9, v[0][1], v[0][2]]]
        combined = trimesh.util.concatenate([
            mesh,
            trimesh.Trimesh(vertices=degenerate_tri, faces=[[0, 1, 2]], process=False),
        ])
        stl_path = tmp_stl(combined, "collapsed.stl")
        stats = convert_file(stl_path, tmp_step)
        assert stats.error is None
        assert stats.n_input_tris == len(mesh.faces) + 1
        assert stats.n_degenerate_collapsed >= 1
        assert stats.n_kept_tris == len(mesh.faces)
        assert stats.watertight is True
        assert stats.is_solid is True

    def test_collinear_triangle_is_rejected(self, tmp_stl, tmp_step):
        # 3 distinct, well-separated (> tolerance apart) but collinear vertices --
        # must survive dedup as 3 distinct indices, then be caught by the shape-ratio
        # (not the absolute-area) degeneracy test.
        mesh = PRIMITIVES["box"].copy()
        v = mesh.vertices
        origin = v[0]
        collinear_tri = [
            list(origin),
            [origin[0] + 1.0, origin[1], origin[2]],
            [origin[0] + 2.0, origin[1], origin[2]],
        ]
        combined = trimesh.util.concatenate([
            mesh,
            trimesh.Trimesh(vertices=collinear_tri, faces=[[0, 1, 2]], process=False),
        ])
        stl_path = tmp_stl(combined, "collinear.stl")
        stats = convert_file(stl_path, tmp_step, tolerance=0.01)
        assert stats.error is None
        assert stats.n_input_tris == len(mesh.faces) + 1
        assert stats.n_degenerate_collapsed == 0, "the 3 points are > tolerance apart, must not collapse"
        assert stats.n_degenerate_zero_area >= 1
        assert stats.n_kept_tris == len(mesh.faces)
        assert stats.watertight is True
        assert stats.is_solid is True

    def test_thin_real_sliver_survives_default_tolerance(self, tmp_step):
        """Regression: a real mesh's legitimately-thin (non-collinear) CAD sliver
        triangle must NOT be rejected just because its area is small relative to
        --tolerance squared. See dedup.py's shape_ratio vs sub-resolution split."""
        origin = [0.0, 0.0, 0.0]
        thin_but_valid = [
            origin,
            [1.0, 0.0, 0.0],
            [0.5, 1e-3, 0.0],  # height 1e-3 over a base of 1.0 -> area 5e-4, well above shape_ratio_eps
        ]
        mesh = trimesh.Trimesh(vertices=thin_but_valid, faces=[[0, 1, 2]], process=False)
        stl_path = mesh_path = None
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as d:
            stl_path = Path(d) / "sliver.stl"
            mesh.export(stl_path.as_posix())
            stats = convert_file(stl_path, tmp_step, tolerance=0.01)
        assert stats.n_degenerate_zero_area == 0
        assert stats.n_kept_tris == 1


class TestMergeCoplanar:
    def test_box_merges_twelve_triangles_into_six_faces(self, tmp_stl, tmp_step):
        mesh, stats = _convert(
            "box", tmp_stl, tmp_step, merge_coplanar_angle=5.0
        )
        assert stats.n_faces_before_merge == 12
        assert stats.n_faces_after_merge == 6

    def test_merge_coplanar_off_by_default(self, tmp_stl, tmp_step):
        mesh, stats = _convert("box", tmp_stl, tmp_step)
        assert stats.n_faces_before_merge is None
        assert stats.n_faces_after_merge is None
        assert stats.n_faces_built == 12

    def test_merge_coplanar_preserves_volume(self, tmp_stl, tmp_step):
        mesh, stats = _convert("box", tmp_stl, tmp_step, merge_coplanar_angle=5.0)
        written_volume = read_step_volume(tmp_step)
        assert abs(written_volume - mesh.volume) / mesh.volume < 1e-4
