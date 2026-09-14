"""The trueform retry ladder: a build whose written STEP lands far off the mesh volume is rebuilt
with a tighter fit, and the closer result is the one served (Schlauchschelle_param v2: -89%)."""
import trimesh
from fastapi.testclient import TestClient

import webapp.server as srv


def _box_step(path):
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer

    w = STEPControl_Writer()
    w.Transfer(BRepPrimAPI_MakeBox(10.0, 10.0, 10.0).Shape(), STEPControl_AsIs)
    w.Write(str(path))


def _convert(monkeypatch, step_volume, cylinders=lambda kw: 2):
    calls = []

    def fake(stl, out, **kw):
        calls.append(kw)
        _box_step(out)
        return {"ok": True, "solids": 1, "openShells": 0, "watertight": True, "freeEdges": 0,
                "meshVolumeMM3": 1000.0, "stepVolumeMM3": step_volume(kw), "volumeDeltaPct": 0.0,
                "facesBeforeUnify": 12, "facesAfterUnify": 6, "facesAfterSmooth": 6, "smooth": True,
                "smoothPlanes": 6, "smoothCylinders": 0, "smoothBuiltCylinders": cylinders(kw),
                "seconds": 0.1, "warnings": [],
                "exit_code": 0}

    monkeypatch.setattr(srv, "convert_native", fake)
    stl = trimesh.creation.box(extents=(10, 10, 10)).export(file_type="stl")
    r = TestClient(srv.app).post("/api/convert", data={"engine": "trueform"},
                                 files={"file": ("box.stl", stl, "application/octet-stream")})
    assert r.status_code == 200, r.text
    return calls, r.json()["stats"]


def test_a_build_far_off_the_mesh_volume_is_rebuilt_with_a_tighter_fit(monkeypatch):
    calls, stats = _convert(monkeypatch, lambda kw: 110.0 if "smooth_tol" not in kw else 1000.5)
    assert [kw.get("smooth_tol") for kw in calls] == [None, 0.01]
    assert any("rebuilt with --smooth-tol 0.01" in w for w in stats["warnings"]), stats["warnings"]


def test_a_build_close_to_the_mesh_volume_is_not_retried(monkeypatch):
    calls, stats = _convert(monkeypatch, lambda kw: 1000.5)
    assert len(calls) == 1
    assert not any("rebuilt with" in w for w in stats["warnings"])


def test_a_retry_that_changes_the_recognised_cylinders_is_not_served(monkeypatch):
    first = lambda kw: "smooth_tol" not in kw and "smooth_angle" not in kw  # noqa: E731
    calls, stats = _convert(monkeypatch, lambda kw: 110.0 if first(kw) else 1000.5,
                            cylinders=lambda kw: 5 if first(kw) else 3)
    assert len(calls) == 3   # both rungs tried, neither kept
    assert not any("rebuilt with" in w for w in stats["warnings"])
