"""When the native engine hangs or fails, the exact shape rebuild still runs on the mesh alone and is served if it
passes its gate; when it does not, the engine's error reaches the user unchanged."""
import trimesh
from fastapi.testclient import TestClient

import webapp.server as srv


def _post(monkeypatch):
    def hung(stl, out, **kw):
        raise srv.NativeTimeout(kw.get("timeout") or 600)

    monkeypatch.setattr(srv, "convert_native", hung)
    monkeypatch.setenv("MESH2STEP_ENGINE_FALLBACK", "1")
    stl = trimesh.creation.cylinder(radius=5.0, height=40.0, sections=64).export(file_type="stl")
    return TestClient(srv.app).post("/api/convert", data={"engine": "trueform"},
                                    files={"file": ("rod.stl", stl, "application/octet-stream")})


def test_a_hung_engine_is_replaced_by_the_rebuild(monkeypatch):
    r = _post(monkeypatch)
    assert r.status_code == 200, r.text
    stats = r.json()["stats"]
    assert stats["feature_method"] == "edgebuild"
    assert stats["smooth_built_cylinders"] == 1 and stats["smooth_built_planes"] == 2


def test_a_hung_engine_without_a_valid_rebuild_still_times_out(monkeypatch):
    monkeypatch.setattr(srv, "_edgebuild_upgrade", lambda stl, out, res: res)
    assert _post(monkeypatch).status_code == 504
