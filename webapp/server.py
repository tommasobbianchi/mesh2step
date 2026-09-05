"""mesh2step web MVP: upload a mesh, convert to STEP server-side, download result.

Backend-convert architecture (OCCT can't run in-browser). The client renders the
mesh locally with three.js for preview; conversion is a server round trip.

Run:  uvicorn webapp.server:app --reload   (from repo root, after `pip install -e .`)
      or:  python webapp/server.py
"""
import base64
import json
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

import trimesh
from mesh2step.cut import apply_cuts, component_labels
from mesh2step.io_mesh import SUPPORTED_EXTENSIONS, MeshLoadError, load_mesh
from mesh2step.native import (
    NativeEngineError,
    NativeTimeout,
    NativeUnavailable,
    convert_native,
    native_available,
)

MAX_UPLOAD_BYTES = 200 * 1024 * 1024  # 200 MB trust-boundary cap
RESULT_TTL_S = 3600  # ponytail: in-memory job registry, 1h TTL. Move to Redis/S3 if multi-worker.
MAX_CONCURRENT_CONVERSIONS = 2   # the engine takes every core and ~1.4 GB per run;
                                 # a third simultaneous conversion makes all three
                                 # miss the deadline instead of two making it
_CONVERT_SLOTS = threading.Semaphore(MAX_CONCURRENT_CONVERSIONS)
_POOL = ThreadPoolExecutor(max_workers=MAX_CONCURRENT_CONVERSIONS + 2,
                           thread_name_prefix="convert")
_PENDING: dict[str, dict] = {}
SYNC_WAIT_S = 20.0    # hold the request this long; past it, hand back a job id
QUEUE_WAIT_S = 240.0  # how long a queued conversion waits for a slot
# With conversion behind a job, nobody is holding a connection open, so the only
# real limit is how long the work deserves. Measured on this host: a
# 64k-triangle gate needs 50-91s of CPU, and at load average 19 -- an unrelated
# service holding a core -- it gets under a fifth of one, which is 300-500s of
# wall clock for the same work. A 300s ceiling failed it purely for being
# unlucky about neighbours.
CONVERT_TIMEOUT_S = 900.0
CANONIZE_MAX_BYTES = 25 * 1024 * 1024  # ~7s at the measured 0.27 s/MB read cost

if not native_available():
    raise NativeUnavailable()

app = FastAPI(title="mesh2step")


@app.on_event("startup")
def _startup_sweep() -> None:
    # nothing is in flight at startup, so anything on disk is an orphan
    _sweep_orphans(time.time())
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
    _sweep_orphans(now)


def _sweep_orphans(now: float) -> None:
    """Reclaim workdirs no token ever pointed at.

    A request that timed out or raised before registering a download token left
    its directory behind for good: the purge above only walks _JOBS. Measured on
    the live server, 598 MB of uploads had accumulated that way, including three
    copies of one 3.2 MB model a user retried. A restart also empties _JOBS while
    the directories survive, so age on disk is the only honest criterion.
    """
    import shutil

    live = {j["path"].parent for j in _JOBS.values()}
    for d in Path(tempfile.gettempdir()).glob("mesh2step_*"):
        try:
            if d in live or not d.is_dir() or now - d.stat().st_mtime <= RESULT_TTL_S:
                continue
            shutil.rmtree(d, ignore_errors=True)
        except OSError:
            pass


def _convert_in_worker(*, stl_path, out_path, workdir, engine, native_engine,
                       schema, native_unify, merge_coplanar_angle, filename, stem,
                       n_in_tris, cut_before, cut_after, repair_info) -> dict:
    """The part that takes minutes. Runs on a worker so the request can let go.

    Bounded by _CONVERT_SLOTS: measured on this host a 64k-triangle gate needs 91s
    alone, and the same work under load average 19 got 18% of a core and blew a
    900s ceiling. Queuing beats thrashing.
    """
    if not _CONVERT_SLOTS.acquire(timeout=QUEUE_WAIT_S):
        __import__("shutil").rmtree(workdir, ignore_errors=True)
        raise HTTPException(503, (
            "The converter is busy with other models right now. "
            "Please try again in a minute — your file was not kept."
        ))
    try:
        res = convert_native(
            stl_path, out_path,
            engine=native_engine, schema=schema, unify_angle=native_unify,
            no_unify=(engine == "faceted" and merge_coplanar_angle is None),
            timeout=CONVERT_TIMEOUT_S,
        )
    except NativeTimeout:
        __import__("shutil").rmtree(workdir, ignore_errors=True)
        raise HTTPException(504, (
            f"This model did not finish within {int(CONVERT_TIMEOUT_S / 60)} minutes. "
            f"It has {n_in_tris:,} triangles — try simplifying the mesh before "
            "uploading, or convert it again when the server is quieter."
        )) from None
    except NativeEngineError as e:
        # covers a killed engine too: a restart or an OOM leaves empty stdout and
        # raises NativeParseError, which used to reach the user as a bare 500.
        __import__("shutil").rmtree(workdir, ignore_errors=True)
        raise HTTPException(502, f"The conversion engine failed: {e}") from e
    finally:
        _CONVERT_SLOTS.release()
    d = _native_stats(res, engine, schema)
    d["backend"] = "native"
    # Triangle count comes from BEFORE the native step, because the binary only
    # ever sees the already-cut, already-repaired mesh. Vertices do NOT: our STL
    # round-trip stores three per triangle, so len(verts) here is always 3x the
    # triangles and says nothing -- the engine's welded count is the real one.
    d["n_input_tris"] = n_in_tris
    if cut_before is not None:
        d["n_cut_tris_before"] = cut_before
        d["n_cut_tris_after"] = cut_after
    if repair_info is not None:
        d.update(repair_info)
    if engine == "faceted" and merge_coplanar_angle is not None:
        d["n_faces_before_merge"] = res.get("facesBeforeUnify")
        d["n_faces_after_merge"] = res.get("facesAfterUnify")
    # don't leak server temp paths to the client
    d["input_path"] = filename
    d["output_path"] = f"{stem}.step"
    if not res.get("ok"):
        __import__("shutil").rmtree(workdir, ignore_errors=True)
        return {"ok": False, "stats": d}

    d["output_size_bytes"] = out_path.stat().st_size

    # Recover the circles the engine's seed band missed. Default ON for trueform:
    # a rebuilt file is the geometry the facets were approximating, and it is
    # smaller (a real lid: 245 faces -> 10, 1.95 MB -> 33 KB). Accepted only if
    # the result is a valid solid, nothing failed, and the volume moved less than
    # 2% -- otherwise the original conversion is kept, silently and intact.
    if (engine == "trueform" and d.get("smooth_cylinders", 0) == 0
            and d.get("smooth_planes", 0) > 12
            and d["output_size_bytes"] <= CANONIZE_MAX_BYTES):
        try:
            from mesh2step.rebuild import rebuild_cylinders

            rebuilt_path = workdir / "rebuilt.step"
            rb = rebuild_cylinders(out_path, rebuilt_path)
            before = d.get("volume") or 0.0
            moved = abs(rb["volume"] - before) / before if before else 1.0
            if (rb.get("ok") and rb.get("valid") and rb["faces_after"] < rb["faces_before"]
                    and moved <= 0.02 and rebuilt_path.exists()):
                rebuilt_path.replace(out_path)
                d["rebuilt"] = True
                d["rebuilt_bands"] = rb["bands"]
                d["n_faces_built"] = rb["faces_after"]
                d["faces_before_rebuild"] = rb["faces_before"]
                d["volume"] = rb["volume"]
                d["output_size_bytes"] = out_path.stat().st_size
                # the engine's volume warnings describe the faceted result we just
                # replaced; keeping them would report a problem we fixed
                d["warnings"] = [w for w in d.get("warnings", []) if "volume" not in w.lower()]
        except Exception:  # noqa: BLE001 - never cost someone their conversion
            pass

    # When nothing was recovered, say WHICH circles were lost -- the radii are
    # the actionable part. Guarded by size: this re-reads the STEP with OCCT, and
    # a 145 MB faceted file measured >300s to read, so it is skipped there.
    if (engine == "trueform" and not d.get("rebuilt")
            and d.get("smooth_cylinders", 0) == 0
            and d["output_size_bytes"] <= CANONIZE_MAX_BYTES):
        try:
            from mesh2step.canonize import find_circles

            circles = find_circles(out_path)
        except Exception:  # noqa: BLE001 - a diagnostic must never fail a conversion
            circles = []
        if circles:
            d["lost_circles"] = [
                {"radius": round(c.radius, 4), "segments": c.segments} for c in circles[:24]
            ]
    token = uuid.uuid4().hex
    _JOBS[token] = {"path": out_path, "name": f"{stem}.step", "ts": time.time()}
    return {"ok": True, "stats": d, "download_token": token}


@app.post("/api/convert")
def convert(
    file: UploadFile = File(...),
    engine: str = Form("faceted"),
    tolerance: str = Form("0.01"),
    merge_coplanar_angle: float | None = Form(None),
    merge_coplanar_linear_tol: float | None = Form(None),
    schema: str = Form("ap214"),
    repair: str | None = Form(None),
    cuts: str | None = Form(None),
    unify_angle: float = Form(5.0),
):
    _purge_expired()

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise HTTPException(400, f"unsupported extension {suffix!r}; supported: {sorted(SUPPORTED_EXTENSIONS)}")
    if engine not in ("faceted", "trueform"):
        raise HTTPException(400, f"invalid engine {engine!r}; must be faceted or trueform")
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

    # repair and cuts are MESH preprocessing (trimesh surgery on verts/tris), not
    # conversion features -- so they run here, on the mesh, and the native engine
    # converts the result. There is no Python fallback: the native binary is
    # required and its absence fails at startup (see the module-level check).
    # ALWAYS normalise through our own loader, not just for non-STL input.
    # The binary takes STL only, and it also rejects an STL whose facet normals
    # are all zero ("unreadable or empty STL") -- which plenty of exporters emit,
    # expecting the reader to derive orientation from vertex winding. Round-tripping
    # costs one load+write and keeps the engine accepting the same inputs as before.
    try:
        verts, tris = load_mesh(in_path)
    except MeshLoadError as e:
        # an unreadable upload is bad input, not a server fault: 400, not a 500
        # traceback, and the temp dir goes with it.
        __import__("shutil").rmtree(workdir, ignore_errors=True)
        raise HTTPException(400, f"could not read mesh: {e.args[0].split(': ', 1)[-1]}")
    n_in_tris = len(tris)
    cut_before = cut_after = None
    repair_info = None

    if parsed_cuts:
        cr = apply_cuts(verts, tris, parsed_cuts)
        verts, tris = cr.verts, cr.tris
        cut_before, cut_after = cr.n_tris_before, cr.n_tris_after
        if len(tris) == 0:
            __import__("shutil").rmtree(workdir, ignore_errors=True)
            return {"ok": False, "stats": {
                "engine": engine, "backend": "native",
                "error": "cut operations removed all triangles",
                "input_path": file.filename, "output_path": f"{stem}.step",
            }}

    if repair is not None:
        from mesh2step import repair as _repair

        rr = _repair.repair_mesh(verts, tris, level=repair)
        verts, tris = rr.verts, rr.tris
        repair_info = {
            "repair_level": repair,
            "n_repair_faces_before": rr.n_faces_before,
            "n_repair_faces_after": rr.n_faces_after,
            "repair_holes_filled": rr.holes_filled,
            "repair_watertight_after": rr.watertight_after,
        }

    stl_path = workdir / "native_input.stl"
    trimesh.Trimesh(vertices=verts, faces=tris, process=False).export(str(stl_path))
    native_engine = "trueform" if engine == "trueform" else "verbatim"
    native_unify = unify_angle if engine == "trueform" else merge_coplanar_angle
    # Faceted with no merge requested must keep one face per triangle, which is
    # what the client already contracts for.
    fut = _POOL.submit(
        _convert_in_worker,
        stl_path=stl_path, out_path=out_path, workdir=workdir, engine=engine,
        native_engine=native_engine, schema=schema, native_unify=native_unify,
        merge_coplanar_angle=merge_coplanar_angle, filename=file.filename, stem=stem,
        n_in_tris=n_in_tris, cut_before=cut_before, cut_after=cut_after,
        repair_info=repair_info,
    )
    try:
        # Small models still answer in one round trip, exactly as before.
        return fut.result(timeout=SYNC_WAIT_S)
    except FuturesTimeout:
        # Big ones get a ticket instead of a dead connection. A 64k-triangle gate
        # needs 91s on an idle host and far longer on a busy one; no browser, proxy
        # or patience survives holding a request open that long.
        job = uuid.uuid4().hex
        _PENDING[job] = {"future": fut, "ts": time.time(), "name": f"{stem}.step"}
        return {"ok": True, "pending": True, "job": job,
                "message": "Still converting — this model is large."}


@app.get("/api/job/{job}")
def job_status(job: str):
    entry = _PENDING.get(job)
    if entry is None:
        raise HTTPException(404, "unknown or expired job")
    fut = entry["future"]
    if not fut.done():
        return {"ok": True, "pending": True, "job": job,
                "elapsed": round(time.time() - entry["ts"], 1)}
    _PENDING.pop(job, None)
    try:
        return fut.result()
    except HTTPException as e:
        raise HTTPException(e.status_code, e.detail) from None



@app.post("/api/preview")
def preview(file: UploadFile = File(...)):
    """Normalise an upload to a binary STL the browser can always render.

    three.js's 3MFLoader cannot follow the production extension (a <component>
    with p:path into 3D/Objects/*.model, which is what Bambu/Orca write), so the
    client preview dies on files this server converts fine. Rather than port that
    resolution into the browser, the client falls back here: same loader as the
    conversion path, so a rendered preview now means the conversion will work.
    """
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise HTTPException(400, f"unsupported extension {suffix!r}")

    workdir = Path(tempfile.mkdtemp(prefix="mesh2step_prev_"))
    try:
        in_path = workdir / f"input{suffix}"
        size = 0
        with in_path.open("wb") as fh:
            while chunk := file.file.read(1 << 20):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(413, f"file exceeds {MAX_UPLOAD_BYTES // (1024*1024)} MB")
                fh.write(chunk)
        try:
            verts, tris = load_mesh(in_path)
        except MeshLoadError as e:
            raise HTTPException(400, f"could not read mesh: {e.args[0].split(': ', 1)[-1]}") from e
        stl = trimesh.Trimesh(vertices=verts, faces=tris, process=False).export(file_type="stl")
        return Response(content=stl, media_type="model/stl")
    finally:
        __import__("shutil").rmtree(workdir, ignore_errors=True)


@app.get("/api/download/{token}")
def download(token: str):
    job = _JOBS.get(token)
    if not job or not job["path"].exists():
        raise HTTPException(404, "result expired or not found")
    return FileResponse(job["path"], media_type="application/step", filename=job["name"])


def _native_stats(res: dict, engine: str, schema: str) -> dict:
    """Map the native RESULT payload onto the stats keys the client renders.

    The reference emits camelCase names (solids, openShells, stepVolumeMM3,
    facesBeforeUnify/facesAfterUnify/facesAfterSmooth, smoothPlanes...); the
    client renders the snake_case names _trueform_stats produces. ``is_solid`` is
    derived, not emitted by the binary.
    """
    smooth = engine == "trueform"
    solids = res.get("solids", 0)
    open_shells = res.get("openShells", 0)
    n_faces_built = res.get("facesAfterSmooth", 0) if smooth else res.get("facesBeforeUnify", 0)
    d = {
        "is_solid": solids > 0 and open_shells == 0,
        "watertight": res.get("watertight", False),
        "n_faces_built": n_faces_built,
        "volume": res.get("stepVolumeMM3", 0.0),
        "mesh_volume": res.get("meshVolumeMM3"),
        "n_input_tris": res.get("triangles", 0),
        "n_input_verts": res.get("vertices", 0),
        "schema": schema,
        "seconds": res.get("seconds", 0.0),
        "warnings": res.get("warnings", []),
        "volume_delta_pct": res.get("volumeDeltaPct", -1.0),
        "engine": engine,
        "error": res.get("error"),
    }
    if smooth:
        d.update(
            {
                "smooth_planes": res.get("smoothPlanes", 0),
                "smooth_cylinders": res.get("smoothCylinders", 0),
                "smooth_fillets": res.get("smoothFillets", 0),
                "smooth_built_components": res.get("smoothBuiltComponents", 0),
                "smooth_reverted_components": res.get("smoothRevertedComponents", 0),
                "faces_after_smooth": res.get("facesAfterSmooth", 0),
            }
        )
    return d


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
