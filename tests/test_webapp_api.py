import sys
import pathlib
from pathlib import Path
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
    assert "did not finish" in detail and "simplifying the mesh" in detail, detail

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
        # backpressure, not a server fault: 429 with a Retry-After the caller
        # can actually obey, in the same plain voice as the triangle limit.
        assert resp.status_code == 429, resp.status_code
        assert "busy" in resp.json()["detail"].lower()
        assert int(resp.headers["Retry-After"]) >= srv.RETRY_AFTER_S
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


def test_a_slow_conversion_returns_a_job_that_can_be_polled(client, monkeypatch, cube_stl_bytes):
    """Past the synchronous window the request hands back a ticket instead of
    holding the connection. A 64k-triangle gate needs 91s on an idle host and far
    longer on a busy one; no browser or proxy survives that."""
    import time as _time

    import webapp.server as srv

    monkeypatch.setattr(srv, "SYNC_WAIT_S", 0.001)   # force the async branch
    resp = client.post(
        "/api/convert",
        files={"file": ("cube.stl", cube_stl_bytes, "application/octet-stream")},
        data={"engine": "faceted"},
    )
    assert resp.status_code == 200, resp.status_code
    body = resp.json()
    assert body.get("pending") is True and body.get("job"), body

    deadline = _time.time() + 120
    while _time.time() < deadline:
        got = client.get(f"/api/job/{body['job']}").json()
        if not got.get("pending"):
            break
        assert got["elapsed"] >= 0
        _time.sleep(0.5)
    else:
        raise AssertionError("job never finished")  # noqa: TRY003

    assert got["ok"] is True, got
    assert got["stats"]["n_faces_built"] > 0
    dl = client.get(f"/api/download/{got['download_token']}")
    assert dl.status_code == 200 and dl.content[:4] == b"ISO-"


def test_an_unknown_job_is_404_not_a_crash(client):
    assert client.get("/api/job/deadbeef").status_code == 404


def test_a_model_above_the_triangle_limit_is_refused_with_the_number(client, monkeypatch):
    """The limit exists because peak RSS is ~24.95 MB per 1k triangles + 128 MB:
    above it the conversion needs more than the cgroup allows, and MemoryHigh
    throttles rather than fails, so it would never finish at any timeout."""
    import webapp.server as srv

    monkeypatch.setattr(srv, "MAX_INPUT_TRIANGLES", 100)
    mesh = trimesh.creation.icosphere(subdivisions=2)      # 320 triangles
    buf = io.BytesIO()
    mesh.export(buf, file_type="stl")
    resp = client.post(
        "/api/convert",
        files={"file": ("big.stl", buf.getvalue(), "application/octet-stream")},
        data={"engine": "trueform"},
    )
    assert resp.status_code == 413, resp.status_code
    detail = resp.json()["detail"]
    assert "320" in detail and "100" in detail, detail
    assert "Reduce mesh" in detail, detail                 # the fix is in the app, not "go use your CAD"


def test_above_the_engine_limit_the_feature_path_is_tried_before_refusing(client, monkeypatch):
    """MAX_INPUT_TRIANGLES is the ENGINE's ceiling, not the converter's.

    Measured: the feature path peaks at 702 MB on 164,996 triangles against the engine's
    ~24.95 MB per 1k, and mechparts/12 and /23 each build one valid closed solid in ~85 s.
    So a mesh over the engine limit is handed to the feature path instead of refused, and
    the engine is never called for it.
    """
    import webapp.server as srv

    monkeypatch.setattr(srv, "MAX_INPUT_TRIANGLES", 100)
    monkeypatch.setattr(srv, "FEATURE_MAX_TRIANGLES", 100_000)
    monkeypatch.setenv("MESH2STEP_FEATURE", "1")
    called = []
    monkeypatch.setattr(srv, "convert_native",
                        lambda *a, **k: called.append("engine") or {"ok": False})
    monkeypatch.setattr(srv, "_feature_upgrade", lambda stl, out, progress=None: (
        Path(out).write_bytes(b"ISO-10303-21;\nENDSEC;\nEND-ISO-10303-21;\n"),
        {"ok": True, "solids": 1, "watertight": True, "freeEdges": 0, "featureMethod": "stepped",
         "smoothBuiltCylinders": 43, "smoothBuiltPlanes": 31, "volumeDeltaPct": 0.02,
         "output": str(out), "warnings": []},
    )[1])

    mesh = trimesh.creation.icosphere(subdivisions=2)      # 320 triangles
    buf = io.BytesIO()
    mesh.export(buf, file_type="stl")
    resp = client.post(
        "/api/convert",
        files={"file": ("big.stl", buf.getvalue(), "application/octet-stream")},
        data={"engine": "trueform"},
    )
    assert resp.status_code == 200, resp.text
    assert called == [], "the engine must not be called for a mesh above its own limit"
    got = resp.json()
    # _native_stats renders the payload in snake_case and tags a validated feature build
    assert got["ok"] and got["stats"]["backend"] == "feature"
    assert got["stats"]["feature_method"] == "stepped"
    assert any("recognised surfaces" in w for w in got["stats"]["warnings"]), got["stats"]


def test_above_the_feature_ceiling_it_is_still_refused(client, monkeypatch):
    """The new path raises the ceiling, it does not remove it."""
    import webapp.server as srv

    monkeypatch.setattr(srv, "MAX_INPUT_TRIANGLES", 100)
    monkeypatch.setattr(srv, "FEATURE_MAX_TRIANGLES", 200)
    monkeypatch.setenv("MESH2STEP_FEATURE", "1")
    mesh = trimesh.creation.icosphere(subdivisions=2)      # 320 triangles
    buf = io.BytesIO()
    mesh.export(buf, file_type="stl")
    resp = client.post(
        "/api/convert",
        files={"file": ("big.stl", buf.getvalue(), "application/octet-stream")},
        data={"engine": "trueform"},
    )
    assert resp.status_code == 413, resp.status_code
    assert "320" in resp.json()["detail"] and "200" in resp.json()["detail"]


def test_the_limit_is_published_so_the_page_can_say_it_first(client):
    body = client.get("/api/limits").json()
    assert body["max_triangles"] == 120_000
    assert body["max_upload_mb"] == 200


# --------------------------------------------------------------------------- #
# admission control
# --------------------------------------------------------------------------- #
def test_a_full_queue_is_refused_at_once_instead_of_waiting_out_queue_wait(
        client, cube_stl_bytes):
    """The point of admission is that the answer arrives NOW.

    Before it, a surge request wrote its upload to disk, joined an unbounded
    executor queue and waited QUEUE_WAIT_S = 240s for a slot it was never going
    to get. 429 + Retry-After is the same answer, immediately, and without the
    file.
    """
    import webapp.server as srv

    taken = [srv._try_admit() for _ in range(srv.MAX_ADMITTED_CONVERSIONS)]
    assert all(ok for ok, _ in taken), "could not fill the admission queue"
    try:
        resp = client.post(
            "/api/convert",
            files={"file": ("cube.stl", cube_stl_bytes, "application/octet-stream")},
            data={"engine": "faceted"},
        )
        assert resp.status_code == 429, resp.status_code
        assert resp.headers.get("Retry-After"), "a refusal without Retry-After is a dead end"
        assert srv.RETRY_AFTER_S <= int(resp.headers["Retry-After"]) <= srv.RETRY_AFTER_MAX_S
    finally:
        for _ in taken:
            srv._release_admission()

    # and nothing leaked: the very next request is served normally
    ok = client.post(
        "/api/convert",
        files={"file": ("cube.stl", cube_stl_bytes, "application/octet-stream")},
        data={"engine": "faceted"},
    )
    assert ok.status_code == 200, ok.status_code
    assert srv._admission_depth() == 0, "an admission slot leaked"


def test_a_slow_host_queues_instead_of_refusing(client, cube_stl_bytes):
    """Surge policy (2026-09-22): a slower measured conversion no longer shrinks admission -- the job waits its
    turn in a bounded FIFO queue (QUEUE_MAX) instead of being refused because its wait passed 240 s."""
    import webapp.server as srv

    before = srv._convert_estimate_s
    depth = 0
    try:
        srv._convert_estimate_s = 900.0
        while srv._try_admit()[0]:
            depth += 1
            assert depth <= srv.MAX_ADMITTED_CONVERSIONS
        assert depth == srv.MAX_ADMITTED_CONVERSIONS == srv.MAX_CONCURRENT_CONVERSIONS + srv.QUEUE_MAX
    finally:
        for _ in range(depth):
            srv._release_admission()
        srv._convert_estimate_s = before


def test_a_queued_upload_gets_its_place_in_line_at_once(client, cube_stl_bytes):
    """Every slot busy: the upload is not held for SYNC_WAIT_S nor refused; the ticket comes back at once with
    its queue position, the job endpoint reports it, and the job runs when a slot frees."""
    import time as _t
    import webapp.server as srv

    held = [srv._CONVERT_SLOTS.acquire(timeout=5) for _ in range(srv.MAX_CONCURRENT_CONVERSIONS)]
    assert all(held)
    try:
        t0 = _t.time()
        r = client.post("/api/convert", files={"file": ("cube.stl", cube_stl_bytes, "application/octet-stream")},
                        data={"engine": "faceted"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("pending") and body.get("queue_position") == 1 and body.get("queue_eta_s") is not None
        assert _t.time() - t0 < srv.SYNC_WAIT_S / 2              # not held for the synchronous wait
        st = client.get(f"/api/job/{body['job']}").json()
        assert st.get("queue_position") == 1
    finally:
        for _ in held:
            srv._CONVERT_SLOTS.release()
    for _ in range(300):
        st = client.get(f"/api/job/{body['job']}").json()
        if not st.get("pending"):
            break
        _t.sleep(0.1)
    assert st.get("ok") and st.get("download_token"), st
    assert srv._admission_depth() == 0 and not srv._QUEUE


def test_the_ai_rebuild_is_capped_in_a_surge(monkeypatch):
    """Each rebuild may call a paid model for minutes; past MESH2STEP_RECON_QUEUE_MAX waiting it answers busy."""
    import webapp.server as srv

    monkeypatch.setenv("MESH2STEP_RECON_QUEUE_MAX", "2")
    monkeypatch.setattr(srv, "_RECON", {"a": {"status": "queued"}, "b": {"status": "running"}})
    assert srv._recon_admit() is False
    monkeypatch.setattr(srv, "_RECON", {"a": {"status": "accepted"}})
    assert srv._recon_admit() is True


def test_a_declared_oversize_upload_is_refused_before_the_body_is_read(client):
    """Content-Length says it is too big; nothing should be spooled to disk."""
    import webapp.server as srv

    resp = client.post(
        "/api/convert",
        content=b"",
        headers={"content-type": "multipart/form-data; boundary=x",
                 "content-length": str(srv.MAX_UPLOAD_BYTES + 1)},
    )
    assert resp.status_code == 413, resp.status_code


def test_the_registries_are_capped_not_merely_expired(tmp_path):
    """TTL bounds how LONG an entry lives, not how many exist.

    Each _JOBS entry also pins a workdir, so an uncapped registry is an uncapped
    disk footprint; under a surge entries arrive far faster than an hour retires
    them.
    """
    import webapp.server as srv

    keep = dict(srv._JOBS)
    srv._JOBS.clear()
    try:
        for i in range(srv.MAX_RETAINED_JOBS + 25):
            d = tmp_path / f"w{i}"
            d.mkdir()
            (d / "out.step").write_bytes(b"x")
            srv._JOBS[f"t{i}"] = {"path": d / "out.step", "name": "out.step",
                                  "ts": 1000.0 + i}
        srv._cap_registries()
        assert len(srv._JOBS) == srv.MAX_RETAINED_JOBS
        assert "t0" not in srv._JOBS, "eviction must take the oldest first"
        assert f"t{srv.MAX_RETAINED_JOBS + 24}" in srv._JOBS, "the newest must survive"
        assert not (tmp_path / "w0").exists(), "an evicted result must free its workdir"
    finally:
        srv._JOBS.clear()
        srv._JOBS.update(keep)


def test_pending_eviction_prefers_finished_tickets_over_running_ones(tmp_path):
    """Dropping a running ticket loses work someone is still waiting on."""
    import webapp.server as srv
    from concurrent.futures import Future

    keep = dict(srv._PENDING)
    srv._PENDING.clear()
    try:
        running = Future()                      # never resolved: still converting
        srv._PENDING["running"] = {"future": running, "ts": 0.0, "name": "a.step"}
        for i in range(srv.MAX_PENDING_JOBS + 5):
            f = Future()
            f.set_result({"ok": True})
            srv._PENDING[f"done{i}"] = {"future": f, "ts": 100.0 + i, "name": "b.step"}
        srv._cap_registries()
        assert len(srv._PENDING) == srv.MAX_PENDING_JOBS
        assert "running" in srv._PENDING, "an in-flight conversion was evicted"
        assert "done0" not in srv._PENDING, "the oldest finished ticket should go first"
    finally:
        srv._PENDING.clear()
        srv._PENDING.update(keep)


def test_the_disk_guard_refuses_when_free_space_cannot_cover_admitted_work(
        client, cube_stl_bytes, monkeypatch):
    """A full filesystem fails far worse than a refused request."""
    import webapp.server as srv

    monkeypatch.setattr(srv, "_disk_free_bytes", lambda: srv.DISK_FLOOR_BYTES // 2)
    resp = client.post(
        "/api/convert",
        files={"file": ("cube.stl", cube_stl_bytes, "application/octet-stream")},
        data={"engine": "faceted"},
    )
    assert resp.status_code == 429, resp.status_code
    assert resp.headers.get("Retry-After")
    assert "space" in resp.json()["detail"].lower()
    assert srv._admission_depth() == 0, "the refused request kept its admission slot"


def _two_spheres_stl():
    import io
    import trimesh as _tm
    a = _tm.creation.icosphere(subdivisions=3, radius=5)
    b = _tm.creation.icosphere(subdivisions=3, radius=5); b.apply_translation([20, 0, 0])
    buf = io.BytesIO(); _tm.util.concatenate([a, b]).export(buf, file_type="stl")
    return buf.getvalue()                                  # 2 x 1280 = 2560 triangles


def test_an_over_limit_mesh_is_convertible_after_reducing_or_trimming_it(client, monkeypatch):
    """No dead end: the ceiling applies to the mesh that is CONVERTED, after the reduction and the trims.
    Trims used to be applied after the check, so trimming a too-big model under the limit was still refused."""
    import json as _json
    import webapp.server as srv

    monkeypatch.setattr(srv, "MAX_INPUT_TRIANGLES", 2000)
    data = _two_spheres_stl()
    f = lambda: {"file": ("two.stl", data, "application/octet-stream")}
    r = client.post("/api/convert", files=f(), data={"engine": "faceted"})
    assert r.status_code == 413 and "Reduce mesh" in r.json()["detail"]      # says where to fix it, in the app
    r = client.post("/api/convert", files=f(), data={"engine": "faceted", "cuts": _json.dumps([{"type": "largest"}])})
    assert r.status_code == 200, r.text
    r = client.post("/api/convert", files=f(), data={"engine": "faceted", "decimate": "ratio", "decimate_keep": "0.5"})
    assert r.status_code == 200, r.text


def test_limits_report_the_feature_ceiling(client):
    import webapp.server as srv
    l = client.get("/api/limits").json()
    assert l["max_triangles"] == srv.MAX_INPUT_TRIANGLES and l["max_triangles_feature"] == srv.FEATURE_MAX_TRIANGLES


def test_edit_previews_trims_then_reduction(client):
    """The page reduces BEFORE converting and shows the result (Tommaso 2026-09-22): /api/edit returns the
    trimmed-then-reduced mesh, with the counts, and that STL is what gets converted."""
    import json as _json
    data = _two_spheres_stl()                              # 2560 triangles, two loose spheres
    f = lambda: {"file": ("two.stl", data, "application/octet-stream")}
    r = client.post("/api/edit", files=f(), data={"decimate": "ratio", "decimate_keep": "0.5"})
    assert r.status_code == 200, r.text
    st = _json.loads(r.headers["X-Mesh-Stats"])
    assert st["n_tris_before"] == 2560 and 1000 <= st["n_tris_after"] <= 1400 and "decimate_dv_pct" in st
    m = trimesh.load(io.BytesIO(r.content), file_type="stl", force="mesh")
    assert len(m.faces) == st["n_tris_after"]
    r = client.post("/api/edit", files=f(), data={"cuts": _json.dumps([{"type": "largest"}]),
                                                    "decimate": "ratio", "decimate_keep": "0.5"})
    st = _json.loads(r.headers["X-Mesh-Stats"])
    assert st["n_tris_trimmed"] == 1280 and st["n_tris_after"] < 1280        # trimmed first, then reduced
    assert client.post("/api/edit", files=f(), data={}).status_code == 400    # nothing asked: refused


def test_the_monitor_needs_a_token_and_reports_the_live_numbers(client, cube_stl_bytes, monkeypatch):
    """The monitoring page's data: token-gated (the site is public through the funnel), and it reports what a
    surge needs -- slots, the queue, requests by endpoint, and the conversions that actually ran."""
    import webapp.server as srv

    monkeypatch.setattr(srv, "ADMIN_TOKEN", "")
    assert client.get("/api/admin/stats").status_code == 503          # not configured: says so
    monkeypatch.setattr(srv, "ADMIN_TOKEN", "sekret")
    assert client.get("/api/admin/stats").status_code == 401
    assert client.get("/api/admin/stats", headers={"x-admin-token": "wrong"}).status_code == 401

    r = client.post("/api/convert", files={"file": ("cube.stl", cube_stl_bytes, "application/octet-stream")},
                    data={"engine": "faceted"})
    assert r.status_code == 200
    d = client.get("/api/admin/stats", headers={"x-admin-token": "sekret"}).json()
    n = d["nodes"][0]
    assert n["slots"]["total"] == srv.MAX_CONCURRENT_CONVERSIONS and n["queue"]["max"] == srv.QUEUE_MAX
    assert n["requests"]["last_5min"]["/api/convert"]["n"] >= 1       # the middleware counted it
    assert n["conversions"]["last_hour"] >= 1 and n["conversions"]["recent"][0]["ok"] is True
    assert n["recon"]["daily_max"] and "memory_mb" in n and n["version"]
