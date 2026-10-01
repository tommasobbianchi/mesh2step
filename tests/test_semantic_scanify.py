"""scanify.py: turn a clean CAD mesh into a scanner-like one (the benchmark input whose clean answer is known)."""
import sys
from pathlib import Path

import numpy as np
import pytest
import trimesh

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/semantic"))
import scanify as S  # noqa: E402


def plate():
    b = trimesh.creation.box((40, 30, 10))
    c = trimesh.creation.cylinder(radius=3, height=20, sections=64)
    return b.difference(c)


def test_scanify_is_dense_noisy_rotated_and_deterministic():
    m = plate()
    s = S.scanify(m, seed=1, noise=0.003, faces=60000)
    assert len(s.faces) >= 50000                                   # dense, uniform-ish tessellation
    # noisy: a flat face is no longer flat - vertex normals scatter
    assert np.std(s.vertex_normals, axis=0).max() > 0.05
    # rotated: its axis-aligned extents differ from the clean part's
    assert not np.allclose(sorted(s.extents), sorted(m.extents), atol=0.5)
    # same volume and size within the noise (it is the same part)
    assert abs(s.volume - m.volume) / m.volume < 0.03
    # same size: a rotation changes the axis-aligned box, not the oriented one
    assert sorted(trimesh.bounds.oriented_bounds(s)[1]) == pytest.approx(sorted(m.extents), abs=1.5)  # noise: +-0.6 mm per face
    # deterministic for a seed
    s2 = S.scanify(m, seed=1, noise=0.003, faces=60000)
    assert np.allclose(s.vertices, s2.vertices)


def test_scanify_noise_scales_with_size():
    m = plate()
    a = S.scanify(m, seed=2, noise=0.001, faces=30000, rotate=False)
    b = S.scanify(m, seed=2, noise=0.01, faces=30000, rotate=False)
    da = np.abs(trimesh.proximity.signed_distance(m, a.vertices[::50])).mean()
    db = np.abs(trimesh.proximity.signed_distance(m, b.vertices[::50])).mean()
    assert db > 4 * da
