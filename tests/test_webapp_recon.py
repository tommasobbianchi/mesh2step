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


def test_a_pending_rebuild_keeps_its_conversion_alive(monkeypatch, tmp_path):
    """The conversion's workdir is where the rebuild runs; expiring it mid-rebuild deleted the work."""
    d = tmp_path / "mesh2step_x"; d.mkdir(); f = d / "a.step"; f.write_text("x")
    old = time.time() - srv.RESULT_TTL_S - 10
    monkeypatch.setitem(srv._JOBS, "tokA", {"path": f, "name": "a.step", "ts": old})
    monkeypatch.setitem(srv._JOBS, "tokB", {"path": f, "name": "b.step", "ts": old})
    monkeypatch.setitem(srv._RECON, "tokA", {"status": "running", "ts": old})
    srv._purge_expired()
    assert "tokA" in srv._JOBS and "tokB" not in srv._JOBS
    srv._JOBS.pop("tokA", None); srv._RECON.pop("tokA", None)


def test_the_rebuild_download_has_its_own_workdir(monkeypatch):
    monkeypatch.setenv("MESH2STEP_RECON", "1")

    def fake(stl_path, workdir):
        workdir.mkdir(parents=True, exist_ok=True); s = workdir / "best.step"; s.write_text("ISO-10303-21; ai")
        return {"status": "accepted", "model": "m", "best_step": str(s), "report": {"valid": True}, "represent": {}}

    monkeypatch.setattr(srv, "_run_recon", fake)
    c = TestClient(srv.app)
    tok = _convert(c)
    s = _poll(c, tok)
    conv, ai = srv._JOBS[tok]["path"], srv._JOBS[s["download_token"]]["path"]
    assert conv.parent not in ai.parents                  # dropping the conversion cannot delete it
    srv._drop_job(tok)
    assert c.get(f"/api/download/{s['download_token']}").status_code == 200


def test_the_rebuild_gets_the_served_step(monkeypatch):
    """The pipeline's STEP is handed to the rebuild (pipeline.step) so junctions are read from it exactly."""
    monkeypatch.setenv("MESH2STEP_RECON", "1")
    seen = {}

    def fake(stl_path, workdir):
        seen["pipeline"] = (workdir / "pipeline.step").exists()
        return {"status": "failed"}

    monkeypatch.setattr(srv, "_run_recon", fake)
    c = TestClient(srv.app)
    _poll(c, _convert(c))
    assert seen["pipeline"] is True


def _fake_recon(calls):
    def run(stl_path, workdir):
        calls.append(stl_path)
        return {"status": "failed", "model": None, "best_step": None, "seconds": 0.0,
                "report": None, "represent": None}
    return run


def test_an_allowlist_refuses_every_other_caller(monkeypatch):
    """MESH2STEP_RECON_ALLOW restricts the paid rebuild to listed TCP peers. TestClient's peer is
    'testclient', so a list without it must queue NOTHING: no rebuild entry, no recon call."""
    monkeypatch.setenv("MESH2STEP_RECON", "1")
    monkeypatch.setenv("MESH2STEP_RECON_ALLOW", "100.103.234.2 100.85.88.58")
    calls = []
    monkeypatch.setattr(srv, "_run_recon", _fake_recon(calls))
    c = TestClient(srv.app)
    tok = _convert(c)
    time.sleep(0.5)
    assert c.get(f"/api/recon/{tok}").status_code == 404      # the UI treats this as: stay silent
    assert calls == []


def test_a_forged_forwarded_for_does_not_pass_the_allowlist(monkeypatch):
    """Identity is the TCP peer. A caller claiming an allowlisted address in X-Forwarded-For is refused."""
    monkeypatch.setenv("MESH2STEP_RECON", "1")
    monkeypatch.setenv("MESH2STEP_RECON_ALLOW", "100.103.234.2")
    calls = []
    monkeypatch.setattr(srv, "_run_recon", _fake_recon(calls))
    c = TestClient(srv.app, headers={"X-Forwarded-For": "100.103.234.2"})
    tok = _convert(c)
    time.sleep(0.5)
    assert c.get(f"/api/recon/{tok}").status_code == 404
    assert calls == []


def test_an_allowlisted_peer_gets_the_rebuild(monkeypatch):
    monkeypatch.setenv("MESH2STEP_RECON", "1")
    monkeypatch.setenv("MESH2STEP_RECON_ALLOW", "testclient")
    calls = []
    monkeypatch.setattr(srv, "_run_recon", _fake_recon(calls))
    c = TestClient(srv.app)
    tok = _convert(c)
    assert _poll(c, tok)["status"] == "failed"
    assert len(calls) == 1


def test_loopback_is_never_allowlisted(monkeypatch):
    """Every proxied public request arrives as 127.0.0.1: listing it by mistake must not open the door."""
    class Req:
        class client: host = "127.0.0.1"
    monkeypatch.setenv("MESH2STEP_RECON_ALLOW", "127.0.0.1 100.103.234.2")
    assert srv._recon_allowed(Req) is False
