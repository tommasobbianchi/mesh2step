"""The result preview: the written STEP comes back tessellated, each triangle tagged by face."""
import base64

import numpy as np
import trimesh
from fastapi.testclient import TestClient

import webapp.server as srv


def test_the_result_preview_tags_every_triangle_with_its_face():
    c = TestClient(srv.app)
    stl = trimesh.creation.box(extents=(10, 10, 10)).export(file_type="stl")
    r = c.post("/api/convert", data={"engine": "faceted"},
               files={"file": ("box.stl", stl, "application/octet-stream")})
    assert r.status_code == 200, r.text
    m = c.get(f"/api/result-mesh/{r.json()['download_token']}")
    assert m.status_code == 200, m.text
    d = m.json()
    pos = np.frombuffer(base64.b64decode(d["positions"]), dtype=np.float32).reshape(-1, 9)
    ids = np.frombuffer(base64.b64decode(d["faceIds"]), dtype=np.uint32)
    assert len(pos) == len(ids) >= 12
    assert {f["type"] for f in d["faces"]} == {"plane"} and ids.max() == len(d["faces"]) - 1
    assert np.allclose(np.abs(pos).max(), 5.0, atol=1e-3)   # same coordinates as the mesh


def test_an_unknown_token_has_no_preview():
    assert TestClient(srv.app).get("/api/result-mesh/nope").status_code == 404
