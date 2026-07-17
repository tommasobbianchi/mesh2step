import sys
import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import trimesh
import pytest
from fastapi.testclient import TestClient
from webapp.server import app


@pytest.fixture(scope="module")
def holed_cube_stl_bytes(tmp_path_factory):
    import numpy as np

    m = trimesh.creation.box((10, 10, 10))
    faces = m.faces[1:]  # drop face 0
    m2 = trimesh.Trimesh(vertices=m.vertices, faces=faces, process=False)
    p = tmp_path_factory.mktemp("data") / "holed_cube.stl"
    m2.export(str(p))
    return p.read_bytes()


@pytest.fixture(scope="module")
def cube_stl_bytes(tmp_path_factory):
    mesh = trimesh.creation.box((10, 10, 10))
    p = tmp_path_factory.mktemp("data") / "cube.stl"
    mesh.export(str(p))
    return p.read_bytes()


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def test_convert_faceted_cube(client, cube_stl_bytes):
    resp = client.post(
        "/api/convert",
        files={"file": ("cube.stl", cube_stl_bytes, "application/octet-stream")},
        data={"tolerance": "0.01", "schema": "ap214"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    s = body["stats"]
    assert s["is_solid"] is True
    assert s["watertight"] is True
    assert s["n_faces_built"] == 12
    assert abs(s["volume"] - 1000.0) < 1e-3
    assert isinstance(body["download_token"], str) and len(body["download_token"]) > 0


def test_download_roundtrip(client, cube_stl_bytes):
    resp = client.post(
        "/api/convert",
        files={"file": ("cube.stl", cube_stl_bytes, "application/octet-stream")},
        data={"tolerance": "0.01", "schema": "ap214"},
    )
    token = resp.json()["download_token"]
    resp = client.get(f"/api/download/{token}")
    assert resp.status_code == 200
    assert resp.content.startswith(b"ISO-10303-21;")


def test_merge_coplanar_collapses_cube(client, cube_stl_bytes):
    resp = client.post(
        "/api/convert",
        files={"file": ("cube.stl", cube_stl_bytes, "application/octet-stream")},
        data={"tolerance": "0.01", "schema": "ap214", "merge_coplanar_angle": "5"},
    )
    assert resp.status_code == 200
    s = resp.json()["stats"]
    assert s["n_faces_before_merge"] == 12
    assert s["n_faces_after_merge"] == 6


def test_unsupported_extension_rejected(client):
    resp = client.post(
        "/api/convert",
        files={"file": ("bad.txt", b"not a mesh", "text/plain")},
        data={"tolerance": "0.01", "schema": "ap214"},
    )
    assert resp.status_code == 400


def test_bad_schema_rejected(client, cube_stl_bytes):
    resp = client.post(
        "/api/convert",
        files={"file": ("cube.stl", cube_stl_bytes, "application/octet-stream")},
        data={"tolerance": "0.01", "schema": "xxx"},
    )
    assert resp.status_code == 400


def test_download_unknown_token_404(client):
    resp = client.get("/api/download/deadbeef")
    assert resp.status_code == 404


def test_convert_repair_fill_makes_solid(client, holed_cube_stl_bytes):
    resp = client.post(
        "/api/convert",
        files={"file": ("holed_cube.stl", holed_cube_stl_bytes, "application/octet-stream")},
        data={"tolerance": "0.01", "schema": "ap214", "repair": "fill"},
    )
    assert resp.status_code == 200
    s = resp.json()["stats"]
    assert s["is_solid"] is True


def test_convert_bad_repair_rejected(client, cube_stl_bytes):
    resp = client.post(
        "/api/convert",
        files={"file": ("cube.stl", cube_stl_bytes, "application/octet-stream")},
        data={"tolerance": "0.01", "schema": "ap214", "repair": "nope"},
    )
    assert resp.status_code == 400
