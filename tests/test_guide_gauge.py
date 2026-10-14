"""The V-gauge on a SCAN (bd projects-vgj7.4): POST /api/guide/{token}/gauge snaps two exactly perpendicular planes to a
90-degree edge, and a build with gauge selections uses them as given.

The scan is the synthetic plate (tests/guided_part.py: 60x40x10 centred at the origin) through scanbench.scanify, as in
tests/test_guide_scan.py. Truth planes are the plate's faces; noise is scanify's normal noise (SIGMA x diagonal).
"""
import pathlib
import sys
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests"), str(ROOT / "tools")]
import guided_part as G  # noqa: E402
import scanbench as B  # noqa: E402

from webapp import server  # noqa: E402

# click point, the two truth planes (unit normal, d) it lies between
EDGES = {"top/front": ([10, -20, 5], [((0, 0, 1), 5), ((0, -1, 0), 20)]),
         "left vertical": ([-30, -20, 0], [((-1, 0, 0), 30), ((0, -1, 0), 20)]),
         "bottom/back": ([10, 20, -5], [((0, 0, -1), 5), ((0, 1, 0), 20)])}


@pytest.fixture(scope="module")
def client():
    return TestClient(server.app)


@pytest.fixture(scope="module")
def scan(tmp_path_factory):
    mesh = G.tessellate(G.part())[0]
    mesh.merge_vertices()
    p = tmp_path_factory.mktemp("g") / "plate_scan.stl"
    m = B.scanify(mesh)
    m.export(str(p))
    tok = "gaug" + "0" * 28
    server._JOBS[tok] = {"path": p, "name": "plate_scan.step", "ts": time.time(), "stl": p}
    return tok, B.SIGMA * float(np.linalg.norm(m.extents))


@pytest.fixture(scope="module")
def tri(client, scan):
    r = client.get(f"/api/guide/{scan[0]}/mesh", params={"scan": "true"})
    assert r.status_code == 200, r.text
    return np.asarray(r.json()["positions"], float).reshape(-1, 3, 3)


def _near(tri, q):
    return int(np.argmin(np.linalg.norm(tri.mean(1) - q, axis=1)))


def _gauge(client, scan, tri, q):
    return client.post(f"/api/guide/{scan[0]}/gauge", json={"triangle": _near(tri, q)})


@pytest.mark.parametrize("name", sorted(EDGES))
def test_gauge_on_a_90_degree_edge(client, scan, tri, name):
    q, truth = EDGES[name]
    r = _gauge(client, scan, tri, q)
    assert r.status_code == 200, r.text
    g = r.json()
    n = [np.array(p["normal"]) for p in g["planes"]]
    assert abs(n[0] @ n[1]) < 1e-9                                   # exactly 90 degrees
    assert abs(g["angle_measured_deg"] - 90) < 3
    assert abs(np.linalg.norm(g["edge"]["direction"]) - 1) < 1e-9
    ends = np.array(g["edge"]["point"]) + np.outer(g["extent"], g["edge"]["direction"])
    for p, nk in zip(g["planes"], n, strict=True):
        tn, td = max(truth, key=lambda t: abs(nk @ t[0]))
        # the fitted plane over the gauge's flange: its corners, against the truth plane
        pts = np.vstack([ends, ends + p["width"] * np.array(p["flange"])])
        pts -= np.outer(pts @ nk - p["d"], nk)
        err = np.abs(pts @ np.array(tn, float) - td).max()
        assert err < 2 * scan[1], (name, err, scan[1])
        assert len(p["triangles"]) >= 6
    assert set(g["triangles"]) == {t for p in g["planes"] for t in p["triangles"]}


@pytest.mark.parametrize("q", [[10, -10, 5],                          # flat: the middle of the top face
                               [0, -5, 0],                            # the 10 mm hole's wall
                               [26 + 4 * 0.7071, 16 + 4 * 0.7071, 0]])  # the r4 fillet
def test_gauge_rejects_no_edge(client, scan, tri, q):
    r = _gauge(client, scan, tri, q)
    assert r.status_code == 400, r.text
    assert r.json()["detail"]


def test_gauge_rejects_bad_triangle(client, scan, tri):
    assert client.post(f"/api/guide/{scan[0]}/gauge", json={"triangle": len(tri)}).status_code == 400


def test_build_with_gauges(client, scan, tri, tmp_path):
    sel = [_gauge(client, scan, tri, EDGES[k][0]).json() for k in sorted(EDGES)]
    assert all(s["kind"] == "gauge" for s in sel)
    for _ in range(300):        # the build fills the rest from detect, which runs in the background
        if server._JOBS[scan[0]]["scan"]["det"].done():
            break
        time.sleep(1)
    r = client.post(f"/api/guide/{scan[0]}/build", json={"selections": sel})
    assert r.status_code == 200, r.text
    step = tmp_path / "g.step"
    step.write_bytes(client.get(f"/api/download/{r.json()['token']}").content)
    _, faces, nsol, valid = G.read_step(step)
    assert nsol == 1 and valid


def test_labels_gauge_wins_planes():
    from mesh2step import guide

    g = {"kind": "gauge", "triangles": [0, 1, 2, 3],
         "planes": [{"normal": [0, 0, 1], "d": 5, "triangles": [0, 1]}, {"normal": [1, 0, 0], "d": 2, "triangles": [2, 3]}]}
    lab = guide.labels(8, [{"kind": "chamfer", "triangles": [1, 4]}, g, {"kind": "cylinder", "triangles": [5, 6]}])
    assert lab["label"][:4] == [0, 0, 1, 1] and lab["label"][4] == 2       # the chamfer lost triangle 1
    assert lab["params"]["0"] == {"normal": [0.0, 0.0, 1.0], "point": [0.0, 0.0, 5.0], "exact": True}
    assert guide.labels(3, [{"kind": "plane", "triangles": [0, 1]}]) == {"label": [0, 0, -1], "kinds": {"0": "plane"}}
