"""orient.py: put a part in its own frame - main axis on Z - before anything else looks at it (owner, 2026-10-03).

The analyser only models extrusions along X/Y/Z; a scan arrives in any pose. The frame comes from the part's
symmetry when it has one, otherwise from its flat faces. Truth on the corpus: the fake scans' rotation is recovered
exactly from the posed reference (same vertex order as the subdivided CAD), and the recovered frame must match it up
to a relabelling of the axes."""
import os
import sys
import time
from pathlib import Path

import numpy as np
import pytest
import shapely.geometry as sg
import trimesh

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/semantic"))
import orient as O  # noqa: E402
import scanify as S  # noqa: E402

SCANS = ROOT.parent / "semantic/runs/semantic/scans"           # the 28 fake scans (worktree sibling)
POSED = ROOT / "runs/refs_posed"
CAD = Path.home() / "corpora/mechparts"


def frame_error_deg(R_found, R_true):
    """Angle between the found frame and the true one, up to a signed permutation of the axes."""
    M = R_found @ R_true                       # identity up to a signed permutation when the frame is right
    P = np.zeros((3, 3))
    for i in range(3):
        j = int(np.argmax(np.abs(M[i]))); P[i, j] = np.sign(M[i, j])
    c = (np.trace(P.T @ M) - 1) / 2
    return float(np.degrees(np.arccos(np.clip(c, -1, 1))))


def posed(mesh, seed):
    R = trimesh.transformations.random_rotation_matrix(rand=np.random.default_rng(seed).random(3))
    m = mesh.copy(); m.apply_transform(R)
    return m, R[:3, :3]


@pytest.fixture(scope="module")
def plate():
    """100 x 60 x 8 plate, two holes on the long centre line: mirror-symmetric, thin along Z."""
    outline = sg.box(-50, -30, 50, 30)
    holes = [sg.Point(x, 0).buffer(6, 64) for x in (-30, 30)]
    return trimesh.creation.extrude_polygon(outline.difference(sg.MultiPolygon(holes)), 8.0)


@pytest.fixture(scope="module")
def flange():
    """A turned part: 80 dia x 10 flange, 40 dia x 50 hub, 20 dia bore - a revolution about Z."""
    prof = [[10, 0], [40, 0], [40, 10], [20, 10], [20, 60], [10, 60]]
    return trimesh.creation.revolve(prof, sections=128)


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_plate_scan_frame_and_main_axis(plate, seed):
    scan = S.scanify(plate, seed=seed, noise=0.003, faces=60000, rotate=False)
    m, R = posed(scan, seed)
    t = time.time(); T, info = O.orient(m); dt = time.time() - t
    assert frame_error_deg(T[:3, :3], R) < 2.0, info
    z = T[2, :3] @ R                            # the found Z, in the plate's own frame
    assert abs(z[2]) > 0.999, ("main axis must be the plate's thickness", z, info)
    x = T[0, :3] @ R
    assert abs(x[0]) > 0.999, ("X must be the long side", x, info)
    out = m.copy(); out.apply_transform(T)
    assert abs(out.bounds[0][2]) < 1e-6 and np.allclose(out.bounds.mean(0)[:2], 0, atol=1e-6)
    assert dt < 10, dt


@pytest.mark.parametrize("seed", [4, 5])
def test_revolution_axis_is_z(flange, seed):
    scan = S.scanify(flange, seed=seed, noise=0.003, faces=60000, rotate=False)
    m, R = posed(scan, seed)
    T, info = O.orient(m)
    z = T[2, :3] @ R
    assert abs(z[2]) > 0.999, (z, info)
    assert info["kind"] == "revolution", info


def test_frame_is_rigid_and_right_handed(plate):
    m, _ = posed(plate, 7)
    T, _ = O.orient(m)
    assert np.allclose(T[:3, :3] @ T[:3, :3].T, np.eye(3), atol=1e-9)
    assert np.linalg.det(T[:3, :3]) > 0


def test_deterministic(plate):
    m, _ = posed(plate, 8)
    assert np.array_equal(O.orient(m)[0], O.orient(m)[0])


def test_prepare_writes_frame_mesh_and_photos_fast(tmp_path):
    scan = SCANS / "11.stl"
    if not scan.exists():
        pytest.skip("corpus scans absent")
    t = time.time()
    res = O.prepare(scan, tmp_path)
    dt = time.time() - t
    assert dt < 20, dt
    assert (tmp_path / "oriented.stl").exists() and (tmp_path / "frame.json").exists()
    pngs = sorted(p.name for p in tmp_path.rglob("*.png"))
    for v in ("PX", "NX", "PY", "NY", "PZ", "NZ", "ISO"):
        assert f"{v}.png" in pngs, pngs
    for a in "XYZ":
        assert f"cut{a}_50.png" in pngs, pngs
    assert res["main_axis"] == "Z" and len(res["T"]) == 4


def true_rotation(name):
    """The fake scan's rotation, replayed: scanify(seed 0) draws one normal per vertex of the subdivided CAD, then the
    rotation. (Kabsch against the posed reference fails: an STL reload reorders the vertices.)"""
    sub = trimesh.load(CAD / f"{name}.stl", force="mesh")
    while len(sub.faces) < 150000:
        sub = sub.subdivide()
    sub.merge_vertices()
    rng = np.random.default_rng(0)
    rng.normal(0.0, 1.0, size=len(sub.vertices))
    return trimesh.transformations.random_rotation_matrix(rand=rng.random(3))[:3, :3]


@pytest.mark.skipif(not (SCANS.exists() and POSED.exists() and CAD.exists()), reason="corpus absent")
def test_corpus_frames():
    """All 28 fake scans: the frame found on the noisy scan aligns as much CAD face area (within 1 deg of an axis) as
    the CAD's own frame, less 0.02, in < 10 s each. Not "equals the true rotation": a symmetric part has many right
    frames, and some CAD frames are not aligned to their own walls (part 12)."""
    names = sorted(p.stem for p in POSED.glob("*.stl"))
    bad, slow = {}, {}
    for n in names:
        scan = trimesh.load(SCANS / f"{n}.stl", force="mesh")
        t = time.time(); T, info = O.orient(scan); dt = time.time() - t
        cad = trimesh.load(CAD / f"{n}.stl", force="mesh"); nc, wc = cad.face_normals, cad.area_faces
        man = lambda F: float(wc[np.abs(nc @ F.T).max(1) > np.cos(np.radians(1))].sum() / wc.sum())
        a, b = man(np.eye(3)), man(T[:3, :3] @ true_rotation(n))
        print(f"{n:>4} cad {a:.3f} found {b:.3f}  {dt:5.1f} s  {info['kind']}", flush=True)
        if b < a - 0.02:
            bad[n] = (round(a, 3), round(b, 3))
        if dt >= 10:
            slow[n] = round(dt, 1)
    assert not bad and not slow, (bad, slow)
