"""The shape rebuild pass: a model the engine ships without its cylinder is served as the exact rebuild,
and the rebuild is refused whenever it would ship fewer cylinder faces than the engine built."""
import trimesh
from fastapi.testclient import TestClient

import webapp.server as srv


def _convert(monkeypatch, engine_cylinders):
    def fake(stl, out, **kw):
        from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
        from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer

        w = STEPControl_Writer()
        w.Transfer(BRepPrimAPI_MakeBox(10.0, 10.0, 10.0).Shape(), STEPControl_AsIs)
        w.Write(str(out))
        return {"ok": True, "solids": 1, "openShells": 0, "watertight": True, "freeEdges": 0,
                "meshVolumeMM3": 3121.0, "stepVolumeMM3": 3121.0, "volumeDeltaPct": 0.0,
                "facesBeforeUnify": 256, "facesAfterUnify": 66, "facesAfterSmooth": 66, "smooth": True,
                "smoothPlanes": 66, "smoothCylinders": 1, "smoothBuiltCylinders": engine_cylinders,
                "triangles": 256, "seconds": 0.1, "warnings": [], "exit_code": 0}

    monkeypatch.setattr(srv, "convert_native", fake)
    stl = trimesh.creation.cylinder(radius=5.0, height=40.0, sections=64).export(file_type="stl")
    r = TestClient(srv.app).post("/api/convert", data={"engine": "trueform"},
                                 files={"file": ("rod.stl", stl, "application/octet-stream")})
    assert r.status_code == 200, r.text
    return r.json()["stats"]


def test_a_faceted_engine_build_is_replaced_by_the_exact_rebuild(monkeypatch):
    stats = _convert(monkeypatch, engine_cylinders=0)
    assert stats["feature_method"] == "edgebuild"
    assert stats["smooth_built_cylinders"] == 1 and stats["smooth_built_planes"] == 2


def test_the_rebuild_never_ships_fewer_cylinders_than_the_engine(monkeypatch):
    stats = _convert(monkeypatch, engine_cylinders=3)
    assert stats["backend"] == "native" and "feature_method" not in stats
