"""A trueform build that does not re-read as a solid (zero-area triangles skipped, open shell written) is rebuilt once
with --force-sew, and served only if that build passes."""
import trimesh
from fastapi.testclient import TestClient

import webapp.server as srv

OK_STATS = {"ok": True, "solids": 1, "openShells": 0, "watertight": True, "freeEdges": 0,
            "meshVolumeMM3": 1000.0, "stepVolumeMM3": 1000.0, "volumeDeltaPct": 0.0,
            "facesBeforeUnify": 12, "facesAfterUnify": 6, "facesAfterSmooth": 6, "smooth": True,
            "smoothPlanes": 6, "smoothCylinders": 0, "smoothBuiltCylinders": 0, "seconds": 0.1,
            "warnings": [], "exit_code": 0}
FAILED = {"ok": False, "error": "post-write verification failed: re-read solid count 0 != written 1", "exit_code": 0}


def _box_step(path):
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer

    w = STEPControl_Writer()
    w.Transfer(BRepPrimAPI_MakeBox(10.0, 10.0, 10.0).Shape(), STEPControl_AsIs)
    w.Write(str(path))


def _post(monkeypatch, sewn_ok, plain_ok=False):
    calls = []

    def fake(stl, out, **kw):
        calls.append(kw)
        if kw.get("no_unify"):
            if not plain_ok:
                return dict(FAILED)
            _box_step(out)
            return dict(OK_STATS)
        if not kw.get("force_sew"):
            return dict(FAILED)
        if not sewn_ok:
            return dict(FAILED)
        _box_step(out)
        return dict(OK_STATS)

    monkeypatch.setattr(srv, "convert_native", fake)
    monkeypatch.setenv("MESH2STEP_EDGEBUILD", "0")
    stl = trimesh.creation.box(extents=(10, 10, 10)).export(file_type="stl")
    r = TestClient(srv.app).post("/api/convert", data={"engine": "trueform"},
                                 files={"file": ("box.stl", stl, "application/octet-stream")})
    return calls, r


def test_a_build_that_does_not_reread_as_a_solid_is_rebuilt_with_force_sew(monkeypatch):
    calls, r = _post(monkeypatch, sewn_ok=True)
    assert r.status_code == 200, r.text
    assert [bool(kw.get("force_sew")) for kw in calls[:2]] == [False, True]
    assert any("rebuilt with --force-sew" in w for w in r.json()["stats"]["warnings"])


def test_a_sewn_build_that_still_fails_is_not_served(monkeypatch):
    calls, r = _post(monkeypatch, sewn_ok=False)
    assert sum(1 for kw in calls if kw.get("force_sew")) == 1
    body = r.json()
    assert body["ok"] is False                                   # the engine's original error is what the user sees
    assert "post-write verification failed" in body["stats"]["error"]


def test_when_sewing_also_fails_the_build_is_retried_without_unify(monkeypatch):
    # mechparts/35: the unify step is what opens the shell, so --no-unify is the last fallback before giving up
    calls, r = _post(monkeypatch, sewn_ok=False, plain_ok=True)
    assert [bool(kw.get("force_sew")) for kw in calls[:2]] == [False, True]
    assert sum(1 for kw in calls if kw.get("no_unify")) == 1
    assert r.json()["ok"] is True
    assert any("--no-unify" in w for w in r.json()["stats"]["warnings"])


def test_a_no_unify_build_that_still_fails_is_not_served(monkeypatch):
    calls, r = _post(monkeypatch, sewn_ok=False, plain_ok=False)
    assert sum(1 for kw in calls if kw.get("no_unify")) == 1
    assert r.json()["ok"] is False
