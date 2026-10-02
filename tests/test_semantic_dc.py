"""afar.simplify_dc: dual contouring - the same four guarantees as afar.simplify, with sharp corners by construction."""
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
    return b.difference(trimesh.creation.cylinder(radius=3, height=20, sections=64))


@pytest.fixture(scope="module")
def scan(clean):
    return S.scanify(clean, seed=3, noise=0.003, faces=60000)


@pytest.fixture(scope="module")
def out(scan):
    return A.simplify_dc(scan, p=0.01)[0]


def test_closed_right_size_and_volume(clean, out):
    assert out.is_watertight
    assert len(out.faces) <= 20000
    assert sorted(out.extents) == pytest.approx(sorted(clean.extents), abs=0.8)
    assert abs(out.volume - clean.volume) / clean.volume < 0.05


def test_flat_faces(out):
    n = np.abs(out.face_normals)
    assert float(out.area_faces[n.max(axis=1) > np.cos(np.radians(3))].sum() / out.area) > 0.85


def test_corners_sharp(out):
    lo, hi = out.bounds
    corners = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
    gaps = [np.linalg.norm(out.vertices - c, axis=1).min() for c in corners]
    assert max(gaps) < 0.25, gaps


def test_bore_survives(out):
    ax = "XYZ"[int(np.argmin(out.extents))]
    holes = P.section_circles(out, ax, 0.5, tol=0.05)
    assert len(holes) == 1 and abs(holes[0]["d"] - 6) < 0.3


def test_open_scan_is_closed(scan):
    holed = scan.copy()
    holed.update_faces(np.arange(len(holed.faces)) % 97 != 0)
    assert A.simplify_dc(holed, p=0.01)[0].is_watertight
