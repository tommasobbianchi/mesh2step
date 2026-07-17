"""mesh2step web MVP: upload a mesh, convert to STEP server-side, download result.

Backend-convert architecture (OCCT can't run in-browser). The client renders the
mesh locally with three.js for preview; conversion is a server round trip.

Run:  uvicorn webapp.server:app --reload   (from repo root, after `pip install -e .`)
      or:  python webapp/server.py
"""
import base64
import json
import tempfile
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

import trimesh
from mesh2step.convert import convert_file
from mesh2step.cut import apply_cuts, component_labels
from mesh2step.io_mesh import SUPPORTED_EXTENSIONS, load_mesh

MAX_UPLOAD_BYTES = 200 * 1024 * 1024  # 200 MB trust-boundary cap
RESULT_TTL_S = 3600  # ponytail: in-memory job registry, 1h TTL. Move to Redis/S3 if multi-worker.

app = FastAPI(title="mesh2step")
_STATIC = Path(__file__).parent / "static"
_JOBS: dict[str, dict] = {}  # token -> {"path": Path, "name": str, "ts": float}


def _purge_expired() -> None:
    now = time.time()
    for token in [t for t, j in _JOBS.items() if now - j["ts"] > RESULT_TTL_S]:
        job = _JOBS.pop(token, None)
        if job:
            try:
                job["path"].parent.exists() and __import__("shutil").rmtree(job["path"].parent, ignore_errors=True)
            except OSError:
                pass


@app.post("/api/convert")
def convert(
    file: UploadFile = File(...),
    tolerance: str = Form("0.01"),
    merge_coplanar_angle: float | None = Form(None),
    merge_coplanar_linear_tol: float | None = Form(None),
    schema: str = Form("ap214"),
    repair: str | None = Form(None),
    cuts: str | None = Form(None),
):
    _purge_expired()

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise HTTPException(400, f"unsupported extension {suffix!r}; supported: {sorted(SUPPORTED_EXTENSIONS)}")
    if schema not in ("ap203", "ap214", "ap242"):
        raise HTTPException(400, f"invalid schema {schema!r}")
    if repair not in (None, "weld", "fill", "solidify"):
        raise HTTPException(400, f"invalid repair {repair!r}; must be weld, fill, solidify, or omitted")

    parsed_cuts = _parse_cuts(cuts)

    workdir = Path(tempfile.mkdtemp(prefix="mesh2step_"))
    stem = Path(file.filename).stem or "model"
    in_path = workdir / f"input{suffix}"
    out_path = workdir / f"{stem}.step"

    size = 0
    with in_path.open("wb") as fh:
        while chunk := file.file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                fh.close()
                __import__("shutil").rmtree(workdir, ignore_errors=True)
                raise HTTPException(413, f"file exceeds {MAX_UPLOAD_BYTES // (1024*1024)} MB limit")
            fh.write(chunk)

    if tolerance == "auto":
        tol = "auto"
    else:
        try:
            tol = float(tolerance)
        except ValueError:
            raise HTTPException(400, f"invalid tolerance {tolerance!r}; must be a number or \"auto\"")
    stats = convert_file(
        in_path,
        out_path,
        tolerance=tol,
        merge_coplanar_angle=merge_coplanar_angle,
        merge_coplanar_linear_tol=merge_coplanar_linear_tol,
        schema=schema,
        repair=repair,
        cuts=parsed_cuts,
    )
    d = stats.as_dict()
    # don't leak server temp paths to the client
    d["input_path"] = file.filename
    d["output_path"] = f"{stem}.step"

    if stats.error:
        __import__("shutil").rmtree(workdir, ignore_errors=True)
        return {"ok": False, "stats": d}

    token = uuid.uuid4().hex
    _JOBS[token] = {"path": out_path, "name": f"{stem}.step", "ts": time.time()}
    return {"ok": True, "stats": d, "download_token": token}


@app.get("/api/download/{token}")
def download(token: str):
    job = _JOBS.get(token)
    if not job or not job["path"].exists():
        raise HTTPException(404, "result expired or not found")
    return FileResponse(job["path"], media_type="application/step", filename=job["name"])


def _parse_cuts(cuts_str: str | None) -> list | None:
    if cuts_str is None:
        return None
    try:
        parsed = json.loads(cuts_str)
    except json.JSONDecodeError as e:
        raise HTTPException(400, f"invalid cuts JSON: {e}")
    if not isinstance(parsed, list):
        raise HTTPException(400, "cuts must be a JSON list")
    return parsed


@app.post("/api/edit")
def edit_mesh(
    file: UploadFile = File(...),
    cuts: str = Form(...),
):
    parsed_cuts = _parse_cuts(cuts)
    if parsed_cuts is None:
        raise HTTPException(400, "cuts parameter is required")

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise HTTPException(400, f"unsupported extension {suffix!r}; supported: {sorted(SUPPORTED_EXTENSIONS)}")

    workdir = Path(tempfile.mkdtemp(prefix="mesh2step_edit_"))
    try:
        in_path = workdir / f"input{suffix}"
        size = 0
        with in_path.open("wb") as fh:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(413, f"file exceeds {MAX_UPLOAD_BYTES // (1024*1024)} MB limit")
                fh.write(chunk)

        verts, tris = load_mesh(in_path)
        cr = apply_cuts(verts, tris, parsed_cuts)
        m = trimesh.Trimesh(vertices=cr.verts, faces=cr.tris, process=False)
        stl_bytes = m.export(file_type="stl")

        stats_header = json.dumps({
            "n_tris_before": cr.n_tris_before,
            "n_tris_after": cr.n_tris_after,
        })
        return Response(
            content=stl_bytes,
            media_type="model/stl",
            headers={"X-Mesh-Stats": stats_header},
        )
    finally:
        import shutil
        shutil.rmtree(workdir, ignore_errors=True)


@app.post("/api/segment")
def segment(
    file: UploadFile = File(...),
    cuts: str | None = Form(None),
):
    import numpy as np

    parsed_cuts = _parse_cuts(cuts)

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise HTTPException(400, f"unsupported extension {suffix!r}; supported: {sorted(SUPPORTED_EXTENSIONS)}")

    workdir = Path(tempfile.mkdtemp(prefix="mesh2step_segment_"))
    try:
        in_path = workdir / f"input{suffix}"
        size = 0
        with in_path.open("wb") as fh:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    fh.close()
                    raise HTTPException(413, f"file exceeds {MAX_UPLOAD_BYTES // (1024*1024)} MB limit")
                fh.write(chunk)

        verts, tris = load_mesh(in_path)
        if parsed_cuts:
            cr = apply_cuts(verts, tris, parsed_cuts)
            verts, tris = cr.verts, cr.tris

        labels = component_labels(verts, tris)

        m = trimesh.Trimesh(vertices=verts, faces=tris, process=False)
        stl_bytes = m.export(file_type="stl")
        stl_b64 = base64.b64encode(stl_bytes).decode("ascii")

        unique, counts = np.unique(labels, return_counts=True)
        comps = [
            {"index": int(u), "face_count": int(c)}
            for u, c in sorted(zip(unique, counts), key=lambda x: x[0])
        ]

        return {
            "stl_base64": stl_b64,
            "face_component": labels.tolist(),
            "components": comps,
        }
    finally:
        import shutil
        shutil.rmtree(workdir, ignore_errors=True)


# static site last so /api/* wins
app.mount("/", StaticFiles(directory=_STATIC, html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
