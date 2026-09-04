import sys
import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import json

import numpy as np
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
def two_box_stl_bytes(tmp_path_factory):
    v0, t0 = trimesh.creation.box((2, 2, 2)).vertices, trimesh.creation.box((2, 2, 2)).faces
    v1, t1 = trimesh.creation.box((5, 5, 5)).vertices, trimesh.creation.box((5, 5, 5)).faces
    v1 = v1 + np.array([10, 0, 0])
    verts = np.concatenate([v0, v1])
    tris = np.concatenate([t0, t1 + len(v0)])
    m = trimesh.Trimesh(vertices=verts, faces=tris, process=False)
    p = tmp_path_factory.mktemp("data") / "two_boxes.stl"
    m.export(str(p))
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


def test_edit_endpoint_reduces_tris(client, two_box_stl_bytes):
    cuts = json.dumps([{"type": "largest"}])
    resp = client.post(
        "/api/edit",
        files={"file": ("two_boxes.stl", two_box_stl_bytes, "application/octet-stream")},
        data={"cuts": cuts},
    )
    assert resp.status_code == 200
    assert len(resp.content) > 0
    stats_header = resp.headers.get("X-Mesh-Stats")
    assert stats_header is not None
    s = json.loads(stats_header)
    assert s["n_tris_after"] < s["n_tris_before"]


def test_convert_with_cuts(client, two_box_stl_bytes):
    resp = client.post(
        "/api/convert",
        files={"file": ("two_boxes.stl", two_box_stl_bytes, "application/octet-stream")},
        data={
            "tolerance": "auto",
            "schema": "ap214",
            "repair": "fill",
            "cuts": json.dumps([{"type": "largest"}]),
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["stats"]["is_solid"] is True


def test_edit_bad_cuts_400(client, cube_stl_bytes):
    resp = client.post(
        "/api/edit",
        files={"file": ("cube.stl", cube_stl_bytes, "application/octet-stream")},
        data={"cuts": "not json"},
    )
    assert resp.status_code == 400


def test_segment_endpoint(client, two_box_stl_bytes):
    resp = client.post(
        "/api/segment",
        files={"file": ("two_boxes.stl", two_box_stl_bytes, "application/octet-stream")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["components"]) == 2
    assert len(body["face_component"]) == 24
    assert isinstance(body["stl_base64"], str) and len(body["stl_base64"]) > 0


def test_convert_trueform_cube(client, cube_stl_bytes):
    resp = client.post(
        "/api/convert",
        files={"file": ("cube.stl", cube_stl_bytes, "application/octet-stream")},
        data={"engine": "trueform", "tolerance": "0.01", "schema": "ap214"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    s = body["stats"]
    assert s["engine"] == "trueform"
    assert s["is_solid"] is True
    assert abs(s["volume"] - 1000.0) < 1e-3


def test_trueform_repair_is_honoured(client, cube_stl_bytes):
    """repair is mesh surgery applied BEFORE conversion, so trueform can take it.

    It used to be refused with 400 because the Python trueform engine has no
    place to apply it. The native engine converts an already-repaired mesh, so
    the refusal is gone and the request must now succeed and report the repair.
    """
    resp = client.post(
        "/api/convert",
        files={"file": ("cube.stl", cube_stl_bytes, "application/octet-stream")},
        data={"engine": "trueform", "repair": "weld", "schema": "ap214"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["stats"]["repair_level"] == "weld"
    assert body["stats"]["backend"] == "native"


def test_trueform_cuts_are_honoured(client, cube_stl_bytes):
    """cuts are mesh surgery too, and are likewise no longer refused."""
    cuts = json.dumps([{"type": "plane", "axis": "z", "offset": 5.0, "keep": "min"}])
    resp = client.post(
        "/api/convert",
        files={"file": ("cube.stl", cube_stl_bytes, "application/octet-stream")},
        data={"engine": "trueform", "cuts": cuts, "schema": "ap214"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["stats"]["backend"] == "native"
    assert body["stats"]["n_cut_tris_before"] is not None


def test_bogus_engine_rejected(client, cube_stl_bytes):
    resp = client.post(
        "/api/convert",
        files={"file": ("cube.stl", cube_stl_bytes, "application/octet-stream")},
        data={"engine": "bogus", "tolerance": "0.01", "schema": "ap214"},
    )
    assert resp.status_code == 400


def test_trueform_download_roundtrip(client, cube_stl_bytes):
    resp = client.post(
        "/api/convert",
        files={"file": ("cube.stl", cube_stl_bytes, "application/octet-stream")},
        data={"engine": "trueform", "tolerance": "0.01", "schema": "ap214"},
    )
    body = resp.json()
    # without the engine field the faceted path runs and still returns a valid
    # STEP, so this assertion is what stops the test passing for the wrong reason.
    assert body["stats"]["engine"] == "trueform"
    token = body["download_token"]
    resp = client.get(f"/api/download/{token}")
    assert resp.status_code == 200
    assert resp.content.startswith(b"ISO-10303-21")


@pytest.fixture(scope="module")
def cube_obj_bytes(tmp_path_factory):
    mesh = trimesh.creation.box((10, 10, 10))
    p = tmp_path_factory.mktemp("data") / "cube.obj"
    mesh.export(str(p))
    return p.read_bytes()


def test_native_faceted_cube(client, cube_stl_bytes):
    resp = client.post(
        "/api/convert",
        files={"file": ("cube.stl", cube_stl_bytes, "application/octet-stream")},
        data={"engine": "faceted", "tolerance": "0.01", "schema": "ap214"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    s = body["stats"]
    assert s["backend"] == "native"
    assert s["is_solid"] is True
    assert abs(s["volume"] - 1000.0) < 1e-3


def test_native_trueform_cube(client, cube_stl_bytes):
    resp = client.post(
        "/api/convert",
        files={"file": ("cube.stl", cube_stl_bytes, "application/octet-stream")},
        data={"engine": "trueform", "tolerance": "0.01", "schema": "ap214"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    s = body["stats"]
    assert s["engine"] == "trueform"
    assert s["backend"] == "native"
    assert s["is_solid"] is True
    assert abs(s["volume"] - 1000.0) < 1e-3


def test_repair_runs_on_the_native_backend(client, holed_cube_stl_bytes):
    """repair no longer forces the Python conversion engine.

    The mesh is repaired here and the native engine converts the result, so the
    backend stays native and the repair is still reported.
    """
    resp = client.post(
        "/api/convert",
        files={"file": ("holed.stl", holed_cube_stl_bytes, "application/octet-stream")},
        data={"engine": "faceted", "repair": "fill", "schema": "ap214"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["stats"]["backend"] == "native"
    assert body["stats"]["repair_level"] == "fill"


def test_native_non_stl_obj(client, cube_obj_bytes):
    resp = client.post(
        "/api/convert",
        files={"file": ("cube.obj", cube_obj_bytes, "application/octet-stream")},
        data={"engine": "faceted", "tolerance": "0.01", "schema": "ap214"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    s = body["stats"]
    assert s["backend"] == "native"
    assert s["is_solid"] is True


@pytest.fixture(scope="module")
def zero_normal_stl_bytes():
    """A binary STL whose facet normals are all zero.

    Plenty of exporters write these and expect the reader to take orientation
    from vertex winding. The native engine rejects such a file outright
    ("unreadable or empty STL") while the Python engine accepts it, so this is
    the shape of input that a naive native switch-over silently loses.
    """
    import io
    import struct

    v = [(0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0),
         (0, 0, 10), (10, 0, 10), (10, 10, 10), (0, 10, 10)]
    f = [(0, 3, 2), (0, 2, 1), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4),
         (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]
    b = io.BytesIO()
    b.write(b"\0" * 80)
    b.write(struct.pack("<I", len(f)))
    for tri in f:
        b.write(struct.pack("<3f", 0.0, 0.0, 0.0))   # the zero normal
        for i in tri:
            b.write(struct.pack("<3f", *v[i]))
        b.write(struct.pack("<H", 0))
    return b.getvalue()


@pytest.mark.parametrize("engine", ["faceted", "trueform"])
def test_zero_normal_stl_converts(client, zero_normal_stl_bytes, engine):
    """A zero-normal STL must convert on both engines, whichever backend runs."""
    resp = client.post(
        "/api/convert",
        files={"file": ("cube.stl", zero_normal_stl_bytes, "application/octet-stream")},
        data={"engine": engine, "schema": "ap214"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True, f"zero-normal STL rejected: {body['stats'].get('error')!r}"
    s = body["stats"]
    assert s["is_solid"] is True
    assert abs(s["volume"] - 1000.0) < 1e-3
