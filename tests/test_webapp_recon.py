"""The AI rebuild runs AFTER a conversion is served, never instead of it (spec webapp-recon.md).

MESH2STEP_RECON=1 queues one recon job per finished conversion on its own single-worker pool;
GET /api/recon/{download_token} reports it; a finished rebuild gets its OWN download token.
The pipeline's result and its download are untouched whatever the rebuild does.
"""
import time

import trimesh
from fastapi.testclient import TestClient

import webapp.server as srv


def _stl_bytes():
    import io
    buf = io.BytesIO(); trimesh.creation.box(extents=[10, 10, 10]).export(buf, file_type="stl")
    return buf.getvalue()


def _convert(client):
    r = client.post("/api/convert", data={"engine": "faceted"},
                    files={"file": ("cube.stl", _stl_bytes(), "application/octet-stream")})
    assert r.status_code == 200, r.text
    body = r.json()
    for _ in range(200):                      # a small faceted cube may still come back pending
        if not body.get("pending"):
            break
        time.sleep(0.1); body = client.get(f"/api/job/{body['job']}").json()
    assert body.get("ok") and body.get("download_token"), body
    return body["download_token"]


def _poll(client, token, until=("accepted", "best_effort", "failed", "unavailable"), secs=30):
    t0 = time.time()
    while time.time() - t0 < secs:
        s = client.get(f"/api/recon/{token}").json()
        if s.get("status") in until:
            return s
        time.sleep(0.1)
    raise AssertionError(f"recon never finished: {s}")


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("MESH2STEP_RECON", raising=False)
    c = TestClient(srv.app)
    tok = _convert(c)
    assert c.get(f"/api/recon/{tok}").json()["status"] == "disabled"


def test_rebuild_runs_after_the_conversion_and_gets_its_own_download(monkeypatch, tmp_path):
    monkeypatch.setenv("MESH2STEP_RECON", "1")
    seen = {}

    def fake_run_recon(stl_path, workdir):
        seen["stl"] = stl_path
        step = workdir / "best.step"; workdir.mkdir(parents=True, exist_ok=True)
        step.write_text("ISO-10303-21; fake")
        return {"status": "accepted", "model": "fake-model", "best_step": str(step), "seconds": 1.5,
                "report": {"valid": True, "faces": 6, "cylinders": 0, "cones": 0, "tori": 0, "planes": 6,
                           "bsplines": 0, "p95_mesh_to_solid": 0.001, "p95_solid_to_mesh": 0.001},
                "represent": {"patches": 0, "curved": 0}}

    monkeypatch.setattr(srv, "_run_recon", fake_run_recon)
    c = TestClient(srv.app)
    tok = _convert(c)
    first = c.get(f"/api/download/{tok}")
    assert first.status_code == 200                      # the pipeline result is served first
    s = _poll(c, tok)
    assert s["status"] == "accepted" and s["model"] == "fake-model"
    assert s["metrics"]["faces"] == 6 and s["metrics"]["valid"] is True
    rtok = s["download_token"]
    assert rtok and rtok != tok
    d = c.get(f"/api/download/{rtok}")
    assert d.status_code == 200 and b"fake" in d.content
    assert str(seen["stl"]).endswith(".stl")
    assert c.get(f"/api/download/{tok}").status_code == 200   # the original is still there


def test_a_crashing_rebuild_never_touches_the_conversion(monkeypatch):
    monkeypatch.setenv("MESH2STEP_RECON", "1")

    def boom(stl_path, workdir):
        raise RuntimeError("model exploded")

    monkeypatch.setattr(srv, "_run_recon", boom)
    c = TestClient(srv.app)
    tok = _convert(c)
    s = _poll(c, tok)
    assert s["status"] == "failed"
    assert c.get(f"/api/download/{tok}").status_code == 200


def test_unknown_token_is_404_when_enabled(monkeypatch):
    monkeypatch.setenv("MESH2STEP_RECON", "1")
    assert TestClient(srv.app).get("/api/recon/deadbeef").status_code == 404
