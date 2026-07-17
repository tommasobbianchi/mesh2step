import sys
import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import numpy as np
import pytest
import trimesh

from mesh2step.cut import apply_cuts, component_labels, CUT_TYPES


def _box_mesh(center, size=(10, 10, 10)):
    v, f = trimesh.creation.box(size).vertices, trimesh.creation.box(size).faces
    v = v + np.array(center)
    return v.astype(np.float64), f.astype(np.int64)


def test_box_keep_inside():
    # small boxes (span +/-1) so the crop region actually contains one of them
    v0, t0 = _box_mesh([0, 0, 0], (2, 2, 2))
    v1, t1 = _box_mesh([10, 0, 0], (2, 2, 2))
    verts = np.concatenate([v0, v1])
    tris = np.concatenate([t0, t1 + len(v0)])
    cr = apply_cuts(verts, tris, [{"type": "box", "min": [-2, -2, -2], "max": [2, 2, 2], "keep": "inside"}])
    assert cr.n_tris_after == len(t0)  # only the origin box survives
    c = cr.verts[cr.tris].mean(axis=1)
    assert np.all(c[:, 0] < 5)  # only centroids near x=0 survive


def test_plane_cut():
    v, t = _box_mesh([0, 0, 0])
    cr = apply_cuts(v, t, [{"type": "plane", "axis": "z", "offset": 0, "side": "max"}])
    # centered cube: side-face triangle centroids sit at z=+/-1.67 (not 0), so
    # keeping z>=0 retains the top face (2) + one triangle of each of 4 sides (4) = 6.
    assert cr.n_tris_after == 6
    c = cr.verts[cr.tris].mean(axis=1)
    assert np.all(c[:, 2] >= -0.01)


def test_largest_component():
    # small box
    vs, ts = _box_mesh([0, 0, 0], (1, 1, 1))
    # large box
    vl, tl = _box_mesh([10, 0, 0], (10, 10, 10))
    verts = np.concatenate([vs, vl])
    tris = np.concatenate([ts, tl + len(vs)])
    cr = apply_cuts(verts, tris, [{"type": "largest"}])
    assert cr.n_tris_after == len(tl)  # only the larger box's faces remain


def test_lasso_ndc():
    # Build a simple box centered at origin with scale [-1, 1]
    v = np.array([
        [-1, -1, -1], [1, -1, -1], [1, 1, -1], [-1, 1, -1],
        [-1, -1, 1], [1, -1, 1], [1, 1, 1], [-1, 1, 1],
    ], dtype=np.float64)
    t = np.array([
        [0, 1, 2], [0, 2, 3], [4, 5, 6], [4, 6, 7],
        [0, 4, 7], [0, 7, 3], [1, 5, 6], [1, 6, 2],
        [0, 1, 5], [0, 5, 4], [3, 2, 6], [3, 6, 7],
    ], dtype=np.int64)

    # Identity matrix -> NDC = xy (vertices already in [-1,1])
    identity = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
    # Polygon covers [-0.5, 0.5] in NDC
    polygon = [[-0.5, -0.5], [0.5, -0.5], [0.5, 0.5], [-0.5, 0.5]]
    cr = apply_cuts(v, t, [{"type": "lasso", "polygon": polygon, "matrix": identity, "keep": "inside"}])
    # Triangles with centroid inside the polygon square should be removed
    c = v[t].mean(axis=1)
    # Centroid of cube is at (0,0,0) -> inside polygon -> removed
    # So all centroids at origin get removed; only tris with centroids outside [-0.5,0.5] survive
    assert cr.n_tris_after < cr.n_tris_before
    assert cr.n_tris_after > 0


def test_bad_op_type():
    v, t = _box_mesh([0, 0, 0])
    with pytest.raises(ValueError):
        apply_cuts(v, t, [{"type": "nope"}])


def test_convert_with_cut_largest():
    from mesh2step.convert import convert_file
    import tempfile

    # Build two-box STL
    vs, ts = _box_mesh([0, 0, 0], (2, 2, 2))
    vl, tl = _box_mesh([10, 0, 0], (5, 5, 5))
    verts = np.concatenate([vs, vl])
    tris = np.concatenate([ts, tl + len(vs)])
    m = trimesh.Trimesh(vertices=verts, faces=tris, process=False)

    with tempfile.TemporaryDirectory() as td:
        in_path = pathlib.Path(td) / "two_boxes.stl"
        out_path = pathlib.Path(td) / "out.step"
        m.export(str(in_path))
        stats = convert_file(
            str(in_path), str(out_path),
            tolerance="auto",
            cuts=[{"type": "largest"}],
        )
        assert stats.is_solid is True
        assert stats.error is None


def test_empty_ops_noop():
    v, t = _box_mesh([0, 0, 0])
    cr = apply_cuts(v, t, [])
    assert cr.n_tris_before == cr.n_tris_after
    assert np.allclose(cr.verts, v)
    assert np.allclose(cr.tris, t)


def test_cut_types():
    assert set(CUT_TYPES) == {"box", "plane", "lasso", "largest", "component"}


class TestComponentLabels:
    def test_two_boxes(self):
        v0, t0 = _box_mesh([0, 0, 0], (2, 2, 2))
        v1, t1 = _box_mesh([10, 0, 0], (5, 5, 5))
        verts = np.concatenate([v0, v1])
        tris = np.concatenate([t0, t1 + len(v0)])
        labels = component_labels(verts, tris)
        assert set(labels) == {0, 1}
        n0 = int((labels == 0).sum())
        n1 = int((labels == 1).sum())
        assert n0 == 12 and n1 == 12

    def test_component_keep_only(self):
        v0, t0 = _box_mesh([0, 0, 0], (2, 2, 2))
        v1, t1 = _box_mesh([10, 0, 0], (5, 5, 5))
        verts = np.concatenate([v0, v1])
        tris = np.concatenate([t0, t1 + len(v0)])
        cr = apply_cuts(verts, tris, [{"type": "component", "index": 0, "keep": "only"}])
        assert cr.n_tris_after == 12
        c = cr.verts[cr.tris].mean(axis=1)
        assert np.all(c[:, 0] < 5)

    def test_component_delete(self):
        v0, t0 = _box_mesh([0, 0, 0], (2, 2, 2))
        v1, t1 = _box_mesh([10, 0, 0], (5, 5, 5))
        verts = np.concatenate([v0, v1])
        tris = np.concatenate([t0, t1 + len(v0)])
        cr = apply_cuts(verts, tris, [{"type": "component", "index": 0, "keep": "delete"}])
        assert cr.n_tris_after == 12
        c = cr.verts[cr.tris].mean(axis=1)
        assert np.all(c[:, 0] > 5)

    def test_component_bad_index(self):
        v, t = _box_mesh([0, 0, 0])
        with pytest.raises(ValueError):
            apply_cuts(v, t, [{"type": "component", "index": 99, "keep": "only"}])
