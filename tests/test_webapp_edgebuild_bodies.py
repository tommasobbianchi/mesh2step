"""A mesh of several separate closed bodies (a print-in-place assembly) is rebuilt body by body and served as one
STEP holding every body as its own exact solid."""
import trimesh
from fastapi.testclient import TestClient

import webapp.server as srv


def test_two_separate_bodies_are_rebuilt_as_two_exact_solids(monkeypatch):
    def fake(stl, out, **kw):
        from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
        from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer

        w = STEPControl_Writer()
        w.Transfer(BRepPrimAPI_MakeBox(10.0, 10.0, 10.0).Shape(), STEPControl_AsIs)
        w.Write(str(out))
        return {"ok": True, "solids": 2, "openShells": 0, "watertight": True, "freeEdges": 0,
                "meshVolumeMM3": 6242.0, "stepVolumeMM3": 6242.0, "volumeDeltaPct": 0.0,
                "facesBeforeUnify": 512, "facesAfterUnify": 132, "facesAfterSmooth": 132, "smooth": True,
                "smoothPlanes": 132, "smoothCylinders": 0, "smoothBuiltCylinders": 0,
                "triangles": 512, "seconds": 0.1, "warnings": [], "exit_code": 0}

    monkeypatch.setattr(srv, "convert_native", fake)
    a = trimesh.creation.cylinder(radius=5.0, height=40.0, sections=64)
    b = trimesh.creation.cylinder(radius=3.0, height=20.0, sections=64)
    b.apply_translation([20.0, 0.0, 0.0])
    stl = trimesh.util.concatenate([a, b]).export(file_type="stl")
    r = TestClient(srv.app).post("/api/convert", data={"engine": "trueform"},
                                 files={"file": ("pair.stl", stl, "application/octet-stream")})
    assert r.status_code == 200, r.text
    stats = r.json()["stats"]
    assert stats["feature_method"] == "edgebuild"
    assert stats["smooth_built_cylinders"] == 2 and stats["smooth_built_planes"] == 4
    assert any("2 bodies" in w for w in stats["warnings"])
