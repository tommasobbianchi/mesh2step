"""mesh2step web MVP: upload a mesh, convert to STEP server-side, download result.

Backend-convert architecture (OCCT can't run in-browser). The client renders the
mesh locally with three.js for preview; conversion is a server round trip.

Run:  uvicorn webapp.server:app --reload   (from repo root, after `pip install -e .`)
      or:  python webapp/server.py
"""
import tempfile
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from mesh2step.convert import convert_file
from mesh2step.io_mesh import SUPPORTED_EXTENSIONS

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
    tolerance: float = Form(0.01),
    merge_coplanar_angle: float | None = Form(None),
    merge_coplanar_linear_tol: float | None = Form(None),
    schema: str = Form("ap214"),
):
    _purge_expired()

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise HTTPException(400, f"unsupported extension {suffix!r}; supported: {sorted(SUPPORTED_EXTENSIONS)}")
    if schema not in ("ap203", "ap214", "ap242"):
        raise HTTPException(400, f"invalid schema {schema!r}")

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

    stats = convert_file(
        in_path,
        out_path,
        tolerance=tolerance,
        merge_coplanar_angle=merge_coplanar_angle,
        merge_coplanar_linear_tol=merge_coplanar_linear_tol,
        schema=schema,
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


# static site last so /api/* wins
app.mount("/", StaticFiles(directory=_STATIC, html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
