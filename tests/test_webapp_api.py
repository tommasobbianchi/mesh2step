import sys
import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import io
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


def test_unreadable_upload_is_400_not_500(client):
    # a file with a supported extension whose bytes are not a mesh: bad input,
    # so a 400 with a reason -- not an unhandled MeshLoadError traceback.
    resp = client.post(
        "/api/convert",
        files={"file": ("junk.stl", b"not an stl at all" * 10, "application/octet-stream")},
        data={"engine": "faceted"},
    )
    assert resp.status_code == 400
    assert "could not read mesh" in resp.json()["detail"]


def _production_3mf_bytes() -> bytes:
    """A 3MF whose only object lives in a second .model part, referenced by a
    <component p:path=...> -- the production extension Bambu/Orca write, and the
    shape three.js's 3MFLoader cannot follow (hence the server preview fallback)."""
    import io
    import zipfile

    box = trimesh.creation.box((10, 10, 10))
    verts = "".join(f'<vertex x="{x}" y="{y}" z="{z}"/>' for x, y, z in box.vertices)
    tris = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in box.faces)
    NS = 'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02"'
    P = 'xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06"'
    sub = (
        f'<?xml version="1.0" encoding="UTF-8"?><model unit="millimeter" {NS} {P}>'
        f'<resources><object id="65537" type="model"><mesh>'
        f"<vertices>{verts}</vertices><triangles>{tris}</triangles>"
        f"</mesh></object></resources><build/></model>"
    )
    root = (
        f'<?xml version="1.0" encoding="UTF-8"?><model unit="millimeter" {NS} {P} '
        f'requiredextensions="p"><resources>'
        f'<object id="1" type="model"><components>'
        f'<component p:path="/3D/Objects/part.model" objectid="65537"/>'
        f"</components></object></resources>"
        f'<build><item objectid="1"/></build></model>'
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/'
            'package/2006/content-types"><Default Extension="model" ContentType="application/'
            'vnd.ms-package.3dmanufacturing-3dmodel+xml"/><Default Extension="rels" ContentType='
            '"application/vnd.openxmlformats-package.relationships+xml"/></Types>',
        )
        z.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.'
            'openxmlformats.org/package/2006/relationships"><Relationship Id="rel0" Target='
            '"/3D/3dmodel.model" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/'
            '3dmodel"/></Relationships>',
        )
        z.writestr("3D/3dmodel.model", root)
        z.writestr("3D/Objects/part.model", sub)
    return buf.getvalue()


def test_preview_normalises_a_production_extension_3mf(client):
    resp = client.post(
        "/api/preview",
        files={"file": ("part.3mf", _production_3mf_bytes(), "application/octet-stream")},
    )
    assert resp.status_code == 200, resp.text
    m = trimesh.load(io.BytesIO(resp.content), file_type="stl")
    assert len(m.faces) == 12
    assert abs(m.volume - 1000.0) < 1e-6


def test_preview_rejects_unreadable_upload(client):
    resp = client.post(
        "/api/preview",
        files={"file": ("junk.stl", b"nope" * 20, "application/octet-stream")},
    )
    assert resp.status_code == 400
    assert "could not read mesh" in resp.json()["detail"]


def test_vertex_count_is_the_engines_welded_one(client, cube_stl_bytes):
    # our STL round-trip stores 3 verts per triangle; a cube has 8, not 36.
    resp = client.post(
        "/api/convert",
        files={"file": ("cube.stl", cube_stl_bytes, "application/octet-stream")},
        data={"engine": "faceted"},
    )
    s = resp.json()["stats"]
    assert s["n_input_tris"] == 12
    assert s["n_input_verts"] == 8


def test_mesh_volume_is_reported_for_the_delta(client, cube_stl_bytes):
    # the panel computes B-Rep-vs-mesh delta itself: the engine's volumeDeltaPct
    # rounds to one decimal, so a conversion warned at 0.01% would read "0.0%".
    resp = client.post(
        "/api/convert",
        files={"file": ("cube.stl", cube_stl_bytes, "application/octet-stream")},
        data={"engine": "trueform"},
    )
    s = resp.json()["stats"]
    assert s["mesh_volume"] > 0
    assert abs(s["mesh_volume"] - 1000.0) < 1e-3


def test_a_timeout_explains_itself_and_cleans_up(client, monkeypatch, cube_stl_bytes):
    """A conversion that runs out of time used to escape as a bare 500 with a
    stack trace, leaving the upload on disk. Measured on the live server: three
    retries of one 3.2 MB model left three directories behind, and 598 MB had
    accumulated that way."""
    import tempfile
    from pathlib import Path

    import webapp.server as srv

    before = set(Path(tempfile.gettempdir()).glob("mesh2step_*"))

    def _timeout(*a, **kw):
        raise srv.NativeTimeout(srv.CONVERT_TIMEOUT_S)

    monkeypatch.setattr(srv, "convert_native", _timeout)
    resp = client.post(
        "/api/convert",
        files={"file": ("cube.stl", cube_stl_bytes, "application/octet-stream")},
        data={"engine": "trueform"},
    )
    assert resp.status_code == 504, resp.status_code
    detail = resp.json()["detail"]
    assert "still converting" in detail and "Exact engine" in detail, detail

    after = set(Path(tempfile.gettempdir()).glob("mesh2step_*"))
    # only NEW directories matter: the same request also sweeps stale orphans, so
    # `after` is legitimately smaller than `before`.
    assert not (after - before), f"workdir leaked: {after - before}"


def test_orphaned_workdirs_are_swept(tmp_path, monkeypatch):
    """Directories no download token points at must still be reclaimed by age."""
    import tempfile
    import time
    from pathlib import Path

    import webapp.server as srv

    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path))
    old = Path(tmp_path) / "mesh2step_old"
    old.mkdir()
    (old / "input.stl").write_bytes(b"x" * 1024)
    import os

    stale = time.time() - srv.RESULT_TTL_S - 60
    os.utime(old, (stale, stale))
    fresh = Path(tmp_path) / "mesh2step_fresh"
    fresh.mkdir()

    srv._sweep_orphans(time.time())
    assert not old.exists(), "stale orphan not reclaimed"
    assert fresh.exists(), "a fresh workdir must not be swept from under a request"


def test_conversions_are_bounded_so_retries_queue_instead_of_thrashing(client, cube_stl_bytes):
    """One conversion of a 64k-triangle model takes 91s alone; under load average
    19 the same work got 18% of a core and blew a 900s ceiling. Beyond the limit a
    request must be told to come back, not allowed to starve the ones running."""
    import webapp.server as srv

    acquired = [srv._CONVERT_SLOTS.acquire(timeout=0)
                for _ in range(srv.MAX_CONCURRENT_CONVERSIONS)]
    assert all(acquired), "could not saturate the slots"
    try:
        srv._CONVERT_SLOTS.acquire = lambda timeout=None: False   # do not wait 30s in a test
        resp = client.post(
            "/api/convert",
            files={"file": ("cube.stl", cube_stl_bytes, "application/octet-stream")},
            data={"engine": "faceted"},
        )
        assert resp.status_code == 503, resp.status_code
        assert "busy" in resp.json()["detail"].lower()
    finally:
        del srv._CONVERT_SLOTS.acquire
        for _ in acquired:
            srv._CONVERT_SLOTS.release()

    # and the limiter must not leak a slot: a normal conversion still works after
    ok = client.post(
        "/api/convert",
        files={"file": ("cube.stl", cube_stl_bytes, "application/octet-stream")},
        data={"engine": "faceted"},
    )
    assert ok.status_code == 200, ok.status_code
