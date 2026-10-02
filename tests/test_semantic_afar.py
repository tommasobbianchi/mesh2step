"""afar.py: see the part from a distance - the coarse, clean shape that keeps its identity (owner, 2026-10-01).

A scanned plate seen at a distance p (fraction of its size) must come back axis-aligned, closed, with flat faces and its
bore, in few triangles - the condition the existing analyser handles."""
import sys
from pathlib import Path

import numpy as np
import pytest
import trimesh

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/semantic"))
import afar as A  # noqa: E402
import probes as P  # noqa: E402
import scanify as S  # noqa: E402


@pytest.fixture(scope="module")
def clean():
    b = trimesh.creation.box((40, 30, 10))
    c = trimesh.creation.cylinder(radius=3, height=20, sections=64)
    return b.difference(c)


@pytest.fixture(scope="module")
def scan(clean):
    return S.scanify(clean, seed=3, noise=0.003, faces=60000)


def axis_aligned_fraction(m, deg=3.0):
    """Share of the surface area whose normal is within deg of a world axis."""
    n = np.abs(m.face_normals)
    return float(m.area_faces[n.max(axis=1) > np.cos(np.radians(deg))].sum() / m.area)


def test_simplify_recovers_a_clean_plate(clean, scan):
    out, T = A.simplify(scan, p=0.01)
    assert out.is_watertight
    assert len(out.faces) <= 20000
    assert sorted(out.extents) == pytest.approx(sorted(clean.extents), abs=0.8)
    assert axis_aligned_fraction(out) > 0.85                       # flat faces came back flat and aligned
    assert abs(out.volume - clean.volume) / clean.volume < 0.05
    ax = "XYZ"[int(np.argmin(out.extents))]
    # the bore survives at this distance: seen from p, a wall is only accurate to ~one pitch (~3 % of r here), so the
    # fine-mesh 2 % circle tolerance is the wrong bar; measured d = 6.06 vs 6.00, centred
    holes = P.section_circles(out, ax, 0.5, tol=0.05)
    assert len(holes) == 1 and abs(holes[0]["d"] - 6) < 0.3
    assert T.shape == (4, 4)                                       # the transform back to the input frame


def test_simplify_closes_an_open_scan(scan):
    holed = scan.copy()
    holed.update_faces(np.arange(len(holed.faces)) % 97 != 0)      # drop ~1 % of the faces: an open, ragged shell
    assert not holed.is_watertight
    out, _ = A.simplify(holed, p=0.01)
    assert out.is_watertight


def test_farther_is_simpler(scan):
    near, _ = A.simplify(scan, p=0.005)
    far, _ = A.simplify(scan, p=0.02)
    assert len(far.faces) < len(near.faces)


def test_corners_come_back_sharp(scan):
    """Seen from afar a face blurs but a corner between two planes is still a corner: the blur's ~1-2 pitch rounding
    (measured 0.6-1.1 mm at p=0.01) must not survive, or the analyser models every edge as a fillet."""
    out, _ = A.simplify(scan, p=0.01)
    lo, hi = out.bounds
    corners = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
    gaps = [np.linalg.norm(out.vertices - c, axis=1).min() for c in corners]
    assert max(gaps) < 0.25, gaps
    assert out.is_watertight
