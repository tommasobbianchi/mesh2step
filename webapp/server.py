"""mesh2step web MVP: upload a mesh, convert to STEP server-side, download result.

Backend-convert architecture (OCCT can't run in-browser). The client renders the
mesh locally with three.js for preview; conversion is a server round trip.

Run:  uvicorn webapp.server:app --reload   (from repo root, after `pip install -e .`)
      or:  python webapp/server.py
"""
import base64
import json
import tempfile
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
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
# The engine takes every core and ~2.0 GB per run (measured 2026-09-07 under the 40-concurrent
# surge: two live stl2step processes at 2022 MB each). A third simultaneous conversion made all
# three miss the deadline instead of two making it -- which is why the default is 2.
#
# MESH2STEP_SLOTS overrides it for CAPACITY MEASUREMENT on the load-test twin only. The default
# is the production value, so a live restart cannot change behaviour unless the variable is set,
# and only mesh2step-loadtest.service sets it.
MAX_CONCURRENT_CONVERSIONS = int(os.environ.get("MESH2STEP_SLOTS", "2"))
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
# The native engine alone gets less than the whole conversion budget: when it hangs (mechparts/29: 3,788 triangles, still
# running after 900 s) the exact shape rebuild still has time to run on its own and serve a validated solid.
NATIVE_TIMEOUT_S = float(os.environ.get("MESH2STEP_NATIVE_TIMEOUT_S", "600"))
# The feature pass (MESH2STEP_FEATURE=1) runs several prototype builders after the engine.
# ponytail: fixed ceiling, per-builder budgets if a slot held this long starves the queue.
FEATURE_TIMEOUT_S = float(os.environ.get("MESH2STEP_FEATURE_TIMEOUT_S", "3600"))


def _app_version() -> str:
    """Commit the service was started from, plus the native engine build it runs."""
    import re
    import subprocess
    try:
        git = ["git", "-C", str(Path(__file__).parent), "describe", "--tags", "--always"]
        sha = subprocess.run(git, capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        sha = ""
    m = re.search(r"mesh2step-native-(v[\w.]+)", os.environ.get("MESH2STEP_NATIVE", ""))
    return " · ".join(p for p in (sha or "unknown", m and f"engine {m.group(1)}") if p)


APP_VERSION = _app_version()
# Measured peak RSS is 24.95 MB per 1k triangles + 128 MB (trueform, on meshes
# that merge nothing). At this limit one conversion peaks near 3.1 GB and two
# concurrent ones plus the server fit inside the unit's 8G MemoryMax -- see
# webapp/deploy/mesh2step.service.d/50-memory.conf. Raise them together or not
# at all: a limit above the cap does not fail, it THROTTLES, and a throttled
# conversion never finishes at any timeout.
MAX_INPUT_TRIANGLES = 120_000
CANONIZE_MAX_BYTES = 25 * 1024 * 1024  # ~7s at the measured 0.27 s/MB read cost

# ---------------------------------------------------------------------------
# Admission control. Everything below bounds how much work may be ACCEPTED; none
# of it touches the conversion itself.
# ---------------------------------------------------------------------------

# How many conversions may exist at once, running or waiting for a slot.
# Derived from the two numbers above it: MAX_CONCURRENT_CONVERSIONS = 2 slots,
# and a large model measured at 50-91s per conversion. Two run, four wait; the
# last of the four starts at ~180s, inside QUEUE_WAIT_S = 240s, and still has
# its full CONVERT_TIMEOUT_S afterwards. A seventh admission cannot be served
# before QUEUE_WAIT_S expires, so accepting it only means holding its upload on
# disk for four minutes and then failing it. Refusing it now is the same answer,
# four minutes earlier and without the disk.
MAX_ADMITTED_CONVERSIONS = MAX_CONCURRENT_CONVERSIONS * 3

# The depth cap above is the ceiling. The binding limit is usually this one: a
# request is admitted only if the queue ahead of it is expected to clear inside
# QUEUE_WAIT_S, using the MEASURED conversion time rather than an assumed one.
# Without it the cap is only correct while conversions take ~90s; when they take
# 210s, admitting six means the last one waits out QUEUE_WAIT_S and fails, which
# is the exact outcome admission control exists to replace with an instant no.

# Floor for Retry-After. The header is computed from the measured queue below,
# but never below this: a browser retrying faster than the shortest realistic
# conversion turns a refusal into a second source of load.
RETRY_AFTER_S = 30

# Ceiling for Retry-After. Past this a caller stops waiting and reloads anyway,
# so a larger number is not information, it is an invitation to a manual retry.
RETRY_AFTER_MAX_S = 600

# Seed for the running estimate of how long one conversion takes, in seconds.
# The value is the 91s upper end of the measurement behind CONVERT_TIMEOUT_S. It
# is only a seed: the real corpus is slower than that (a 19,042-triangle bench
# model measured >210s on trueform on this host), and a queue sized on a stale
# guess is exactly the thing that makes a caller wait QUEUE_WAIT_S and then fail.
CONVERT_ESTIMATE_SEED_S = 91.0
# Weight of the newest conversion in that estimate. 0.25 crosses most of the gap
# between the seed and reality within four conversions -- fast enough to react to
# a heavy model, slow enough that one quick 12-triangle box does not reopen the
# gates.
CONVERT_ESTIMATE_ALPHA = 0.25

# Ceiling on the finished-result registry. Each entry pins one workdir on disk
# for RESULT_TTL_S = 3600s. At the sustained ceiling of 2 concurrent conversions
# at ~50s each, an hour produces ~144 results, so 256 holds a full TTL window of
# real traffic with headroom; past that we are being flooded, not used, and the
# oldest finished result is the one nobody is coming back for.
MAX_RETAINED_JOBS = 256

# Ceiling on the in-flight job-ticket registry. Only an ADMITTED conversion can
# create a ticket, so at most MAX_ADMITTED_CONVERSIONS of these are ever live;
# the rest are finished results whose owner never polled /api/job. Sized well
# above the live bound so eviction can only ever fall on a finished one.
MAX_PENDING_JOBS = 64

# Worst-case disk one admitted conversion can occupy: the upload itself
# (MAX_UPLOAD_BYTES), the STL round-trip written for the engine (50 B/triangle,
# 6 MB at MAX_INPUT_TRIANGLES), and the STEP it produces. The STEP term is
# measured, not assumed: across 55 STL/STEP pairs in the bench corpus the worst
# ratio is 2,292 bytes per triangle, which is 275 MB at MAX_INPUT_TRIANGLES.
# 200 + 6 + 275 = 481 MB, rounded up.
DISK_PER_JOB_BYTES = 512 * 1024 * 1024

# Free space we refuse to spend, whatever the queue looks like. A full
# filesystem does not fail one request, it breaks the service, the logs and the
# static site at once; 2 GB is enough for the retained results and the OS to
# keep functioning while the TTL sweep catches up.
DISK_FLOOR_BYTES = 2 * 1024 * 1024 * 1024

_SCRATCH_DIR = Path(tempfile.gettempdir())  # where every workdir is created

_admission_lock = threading.Lock()
_admitted = 0  # conversions accepted and not yet finished
_convert_estimate_s = CONVERT_ESTIMATE_SEED_S  # EWMA of measured conversion time


def observe_convert_seconds(seconds: float) -> None:
    """Feed one finished conversion into the estimate the queue is sized on."""
    global _convert_estimate_s
    seconds = min(max(float(seconds), 1.0), CONVERT_TIMEOUT_S)
    with _admission_lock:
        _convert_estimate_s = ((1 - CONVERT_ESTIMATE_ALPHA) * _convert_estimate_s
                               + CONVERT_ESTIMATE_ALPHA * seconds)


def _wait_estimate_s(ahead: int) -> float:
    """How long a request with `ahead` conversions in front of it should expect.

    `ahead` includes the ones running: a newcomer waits for a slot, and slots are
    freed at MAX_CONCURRENT_CONVERSIONS per conversion-time.
    """
    return max(0.0, ahead - MAX_CONCURRENT_CONVERSIONS + 1) / \
        MAX_CONCURRENT_CONVERSIONS * _convert_estimate_s


def _admission_depth() -> int:
    with _admission_lock:
        return _admitted


def _would_admit() -> bool:
    """Cheap, lock-free-enough read of the same predicate _try_admit enforces."""
    with _admission_lock:
        return (_admitted < MAX_ADMITTED_CONVERSIONS
                and _wait_estimate_s(_admitted) <= QUEUE_WAIT_S)


def _try_admit() -> tuple[bool, float]:
    """Take one admission slot, or refuse with the wait we could not promise."""
    global _admitted
    with _admission_lock:
        wait = _wait_estimate_s(_admitted)
        if _admitted >= MAX_ADMITTED_CONVERSIONS or wait > QUEUE_WAIT_S:
            return False, wait
        _admitted += 1
        return True, wait


def _release_admission() -> None:
    global _admitted
    with _admission_lock:
        _admitted = max(0, _admitted - 1)


def _retry_after(wait_s: float | None = None) -> int:
    if wait_s is None:
        wait_s = _wait_estimate_s(_admission_depth())
    return int(min(max(wait_s, RETRY_AFTER_S), RETRY_AFTER_MAX_S))


def _busy(detail: str, wait_s: float | None = None) -> HTTPException:
    """429 with a Retry-After, in the same plain voice as the triangle limit."""
    return HTTPException(429, detail,
                         headers={"Retry-After": str(_retry_after(wait_s))})


def queue_full_message(wait_s: float) -> str:
    minutes = max(1, int(round(_retry_after(wait_s) / 60)))
    return (
        f"The converter is full — it runs {MAX_CONCURRENT_CONVERSIONS} models at "
        f"a time and everything waiting would take about "
        f"{minutes} minute{'s' if minutes != 1 else ''} to clear. Nothing was "
        "uploaded, so nothing is lost: please send it again in a few minutes."
    )


def _disk_headroom_bytes() -> int:
    """Free bytes we must keep to finish the work already admitted, plus floor."""
    return DISK_FLOOR_BYTES + _admission_depth() * DISK_PER_JOB_BYTES


def _disk_free_bytes() -> int:
    try:
        return __import__("shutil").disk_usage(_SCRATCH_DIR).free
    except OSError:
        return 0  # unreadable scratch area is not a reason to accept more work


DISK_FULL_MESSAGE = (
    "The server is out of working space for new conversions right now. Nothing "
    "was uploaded — results are cleared as they expire, so please try again in "
    "a minute."
)

if not native_available():
    raise NativeUnavailable()

app = FastAPI(title="mesh2step")

# Endpoints that write an upload to disk before they can judge it. The gate
# below runs before the body is read, so it protects the disk as well as the CPU.
_UPLOAD_PATHS = frozenset({"/api/convert", "/api/preview", "/api/edit", "/api/segment"})

# Below this, reading the body costs one read() and refusing early buys nothing,
# while answering after the body is consumed is a clean, well-framed HTTP
# exchange. It is the same 1 MB chunk every upload loop in this file already
# reads. Above it, refusing before the body is the whole point.
PREREAD_REFUSE_MIN_BYTES = 1024 * 1024


@app.middleware("http")
async def _admission_gate(request: Request, call_next):
    """Refuse what we cannot serve BEFORE the body is read.

    Starlette parses multipart before the endpoint function runs, spooling
    anything over 1 MB to disk. By then a refusal has already cost the upload it
    was meant to avoid. Content-Length is advisory, so this is an optimisation,
    not the bound: /api/convert re-checks admission authoritatively.
    """
    if request.method != "POST" or request.url.path not in _UPLOAD_PATHS:
        return await call_next(request)

    try:
        declared = int(request.headers.get("content-length") or 0)
    except ValueError:
        declared = 0

    if declared > MAX_UPLOAD_BYTES:
        return JSONResponse(
            {"detail": f"file exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit"},
            status_code=413,
        )

    if declared >= PREREAD_REFUSE_MIN_BYTES:
        if _disk_free_bytes() < _disk_headroom_bytes():
            return JSONResponse({"detail": DISK_FULL_MESSAGE}, status_code=429,
                                headers={"Retry-After": str(RETRY_AFTER_S),
                                         "X-Refusal": "preread-disk"})
        if request.url.path == "/api/convert" and not _would_admit():
            wait_s = _wait_estimate_s(_admission_depth())
            return JSONResponse({"detail": queue_full_message(wait_s)},
                                status_code=429,
                                headers={"Retry-After": str(_retry_after(wait_s)),
                                         "X-Refusal": "preread-queue"})

    return await call_next(request)


@app.middleware("http")
async def _server_timer(request: Request, call_next):
    """Time every upload request SERVER-SIDE, from first byte seen to response.

    Exists because the client number is not the gate. A load generator running 40
    threads measured 429 p50 = 1.178 s while the server's own refusal path took
    0.001 s: the second was the generator encoding multipart, not the service.
    Only the upload paths are timed -- static assets would drown the signal.
    """
    if request.url.path not in _UPLOAD_PATHS:
        return await call_next(request)
    t0 = time.monotonic()
    resp = await call_next(request)
    el = time.monotonic() - t0
    resp.headers["X-Server-Time"] = f"{el:.4f}"
    # A 429 with no X-Refusal was raised INSIDE the endpoint, which Starlette only
    # reaches after the multipart body is parsed -- so its latency is mostly the
    # upload. A pre-read refusal never touches the body. Conflating the two is how
    # "429 p50" ended up meaning two different things in two different reports.
    kind = resp.headers.get("X-Refusal") or (
        "postparse" if resp.status_code == 429 else "served")
    print(f"SRVREQ {resp.status_code} {request.url.path} {el:.4f} {kind}",
          file=sys.stderr, flush=True)
    return resp

@app.on_event("startup")
def _startup_sweep() -> None:
    # nothing is in flight at startup, so anything on disk is an orphan
    _sweep_orphans(time.time())
_STATIC = Path(__file__).parent / "static"
_JOBS: dict[str, dict] = {}  # token -> {"path": Path, "name": str, "ts": float}


def _drop_job(token: str) -> None:
    job = _JOBS.pop(token, None)
    if not job:
        return
    try:
        __import__("shutil").rmtree(job["path"].parent, ignore_errors=True)
    except OSError:
        pass


def _cap_registries() -> None:
    """Keep the two in-memory registries bounded, oldest finished first.

    TTL alone is not a bound: it caps how LONG an entry lives, not how many
    exist. A surge produces entries far faster than an hour retires them, and
    each _JOBS entry also pins a workdir, so an unbounded registry is an
    unbounded disk footprint as well.
    """
    # _JOBS is finished results only -- every entry here is evictable, and the
    # oldest is the one least likely to still be wanted.
    while len(_JOBS) > MAX_RETAINED_JOBS:
        _drop_job(min(_JOBS, key=lambda t: _JOBS[t]["ts"]))

    if len(_PENDING) <= MAX_PENDING_JOBS:
        return
    # Finished-but-unpolled tickets go first; a running conversion is only
    # dropped if somehow nothing finished is left, and then the oldest, because
    # dropping it loses work someone is still waiting on.
    order = sorted(_PENDING.items(), key=lambda kv: (not kv[1]["future"].done(), kv[1]["ts"]))
    for job, _entry in order[:len(_PENDING) - MAX_PENDING_JOBS]:
        _PENDING.pop(job, None)


def _purge_expired() -> None:
    now = time.time()
    for token in [t for t, j in _JOBS.items() if now - j["ts"] > RESULT_TTL_S]:
        _drop_job(token)
    for job in [j for j, e in _PENDING.items()
                if e["future"].done() and now - e["ts"] > RESULT_TTL_S]:
        _PENDING.pop(job, None)
    _cap_registries()
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


def _feature_upgrade(stl_path, out_path) -> dict | None:
    """Replace the engine STEP with a feature-level build when one qualifies (MESH2STEP_FEATURE=1).

    Runs in its own process group so an OCCT crash or hang in a prototype builder costs the
    attempt, never the worker; a timeout kills the whole group. None = engine output kept.
    """
    import signal
    import subprocess

    cand = Path(out_path).with_name("feature.step")
    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", "mesh2step.feature", str(stl_path), "-o", str(cand),
             "--no-fallback", "--engine-step", str(out_path)],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, start_new_session=True,
        )
        stdout, _ = proc.communicate(timeout=FEATURE_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()
        return None
    except OSError:
        return None
    lines = [ln for ln in stdout.splitlines() if ln.startswith("RESULT ")]
    if proc.returncode != 0 or not lines or not cand.exists():
        return None
    cand.replace(out_path)
    res = json.loads(lines[-1][7:])
    res["output"] = str(out_path)
    return res


# A trueform STEP whose re-read volume is far off the mesh has a face that did not survive the
# write (Schlauchschelle_param v2: -89%, the outer ring wall lost). A tighter fit tolerance, then a
# stricter near-flat gate, build that face differently; a retry is kept only if it lands closer
# AND recognises the same number of cylinders -- it repairs the write, it must not trade shape for
# volume (measured: L08_pillow_block 5 -> 3 built cylinders, L04_chamf_cube_recon 0 -> 5 invented,
# normal CADScore 73.14 -> 72.60 without this condition).
RETRY_DV_PCT = 1.0
RETRY_LADDER = ({"smooth_tol": 0.01}, {"smooth_angle": 1.0})


def _volume_error_pct(res: dict) -> float:
    m, s = res.get("meshVolumeMM3"), res.get("stepVolumeMM3")
    return abs(s - m) / abs(m) * 100.0 if m and s is not None else float("inf")


def _retry_broken_trueform(stl_path, out_path, res, *, schema, unify_angle) -> dict:
    if res.get("solids") != 1 or res.get("openShells"):
        return res  # an open or multi-body result has no single volume to compare
    best, err = res, _volume_error_pct(res)
    for i, extra in enumerate(RETRY_LADDER):
        if err <= RETRY_DV_PCT:
            break
        cand = Path(out_path).with_name(f"retry{i}.step")
        try:
            r = convert_native(stl_path, cand, engine="trueform", schema=schema,
                               unify_angle=unify_angle, timeout=CONVERT_TIMEOUT_S, **extra)
        except (NativeTimeout, NativeEngineError):
            continue
        e = _volume_error_pct(r)
        sound = (r.get("ok") and r.get("solids") == 1 and not r.get("openShells")
                 and r.get("smoothBuiltCylinders") == res.get("smoothBuiltCylinders"))
        if sound and e < err and cand.exists():
            cand.replace(out_path)
            flag = " ".join(f"--{k.replace('_', '-')} {v}" for k, v in extra.items())
            r["output"] = str(out_path)
            note = (f"the first build's STEP was {err:.1f}% off the mesh volume; "
                    f"rebuilt with {flag} ({e:.2f}%)")
            r["warnings"] = [note, *(r.get("warnings") or [])]
            best, err = r, e
    return best


# The shape rebuild (tools/feature_recon/edgebuild.py): every mesh region one fitted analytic surface,
# every edge the exact intersection of its two surfaces, every corner their exact common point. The
# engine output stays unless the rebuild is a valid single closed solid on the mesh, and never with
# fewer cylinder faces than the engine built. cadbench normal 67 -> 86 of 103 models with exact face
# types (2026-09-14); Bracket_40 0 -> 4 hole cylinders, Schlauchschelle a valid solid with its cones.
EDGEBUILD = Path(__file__).resolve().parents[1] / "tools" / "feature_recon" / "edgebuild.py"
# adaptive probing around the builder: a body that misses the gate is retried with variants picked by its failure class
# (user request 2026-09-15); MESH2STEP_EDGEBUILD_PROBE=0 runs the plain builder
EDGEBUILD_PROBE = EDGEBUILD.with_name("probe.py")
PROBE_ON = os.environ.get("MESH2STEP_EDGEBUILD_PROBE", "1") != "0"
EDGEBUILD_TIMEOUT_S = float(os.environ.get("MESH2STEP_EDGEBUILD_TIMEOUT_S", "900"))
# ponytail: not yet measured above this size (memory of the Python fit in the service cgroup)
EDGEBUILD_MAX_TRIS = int(os.environ.get("MESH2STEP_EDGEBUILD_MAX_TRIS", "60000"))
EDGE_MAX_DV_PCT = 1.0        # exact curved faces vs chord mesh: the corpus maximum was 0.42 %
EDGE_MAX_P95_REL = 0.005     # of the diagonal, same limit as the feature pass


def _edgebuild_upgrade(stl_path, out_path, res) -> dict:
    """Replace the engine STEP with the exact-intersection shape rebuild when it passes the gate.

    Runs in its own process group like the feature pass: a crash or hang costs this attempt, never
    the worker. `res` is returned unchanged whenever the rebuild fails or is refused.
    """
    import ast
    import signal
    import subprocess

    if (os.environ.get("MESH2STEP_EDGEBUILD", "1") == "0" or not res.get("ok")
            or (res.get("triangles") or 0) > EDGEBUILD_MAX_TRIS):
        return res
    deadline = time.time() + EDGEBUILD_TIMEOUT_S

    def _run(args, env_extra, script=EDGEBUILD):
        try:
            proc = subprocess.Popen(
                [sys.executable, str(script), *args], env=dict(os.environ, **env_extra),
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, start_new_session=True,
            )
            stdout, _ = proc.communicate(timeout=max(1.0, deadline - time.time()))
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
            return None, ""
        except OSError:
            return None, ""
        return proc.returncode, stdout

    # a mesh of several closed bodies (print-in-place assembly, broom holder: bar + two clip arms 0.34 mm apart) is
    # rebuilt body by body, each gated on its own, and served as one STEP of that many solids
    rc, out = _run([str(stl_path), str(Path(out_path).with_name("count.step"))], {"EB_COUNT_BODIES": "1"})
    count = next((ln for ln in out.splitlines() if ln.startswith("BODIES ")), None)
    n_bodies = int(count.split()[1]) if rc == 0 and count else 1
    cands, metrics = [], []
    for k in range(n_bodies):
        cand = Path(out_path).with_name(f"edge{k}.step")
        env_b = {"EB_BODY": str(k)} if n_bodies > 1 else {}
        if PROBE_ON and EDGEBUILD_PROBE.exists():
            # the probe shares this body's remaining time; its stdout ends with the winning build's RESULT line
            env_b["EB_PROBE_BUDGET"] = str(max(1.0, (deadline - time.time()) / (n_bodies - k) - 5))
        rc, out = _run([str(stl_path), str(cand)], env_b,
                       EDGEBUILD_PROBE if PROBE_ON and EDGEBUILD_PROBE.exists() else EDGEBUILD)
        line = next((ln for ln in reversed(out.splitlines()) if ln.startswith("RESULT ")), None)
        cands.append(cand)
        if rc != 0 or line is None or not cand.exists():
            break
        m = ast.literal_eval(line[7:].split(" radii ")[0])
        if not (m["valid"] and m["solids"] == 1 and m["free_edges"] == 0
                and abs(m["dv_pct"]) <= EDGE_MAX_DV_PCT and m["dist_p95"] <= EDGE_MAX_P95_REL * m["diag"]):
            break
        metrics.append(m)
    before = res.get("smoothBuiltCylinders") or 0
    final = Path(out_path).with_name("edge.step")
    ok = len(metrics) == n_bodies and sum(m["cylinders"] for m in metrics) >= before
    if ok and n_bodies > 1:
        rc, out = _run(["--combine", str(final), *map(str, cands)], {})
        ok = rc == 0 and f"COMBINED {n_bodies}" in out
    elif ok:
        cands[0].replace(final)
    for c in cands:
        c.unlink(missing_ok=True)
    if not ok or not final.exists():
        final.unlink(missing_ok=True)
        return res
    final.replace(out_path)
    planes = sum(m["planes"] for m in metrics); cyls = sum(m["cylinders"] for m in metrics)
    faces = sum(m["faces"] for m in metrics); volume = sum(m["volume"] for m in metrics)
    dv = metrics[0]["dv_pct"] if n_bodies == 1 else 100.0 * (volume / sum(m["mesh_volume"] for m in metrics) - 1.0)
    bodies = f"{n_bodies} bodies, " if n_bodies > 1 else ""
    note = (f"shape rebuilt from exact surfaces: {bodies}{planes} planes, {cyls} cylinders, "
            f"{faces - planes - cyls} other curved faces (engine built {before} cylinders; volume {dv:+.2f}% vs mesh)")
    return dict(res, output=str(out_path), solids=n_bodies, openShells=0, watertight=True, freeEdges=0,
                stepVolumeMM3=volume, volumeDeltaPct=dv, facesAfterUnify=faces,
                facesAfterSmooth=faces, smoothPlanes=planes, smoothCylinders=cyls,
                smoothBuiltPlanes=planes, smoothBuiltCylinders=cyls,
                featureMethod="edgebuild", warnings=[note, *(res.get("warnings") or [])])


def _convert_in_worker(*, stl_path, out_path, workdir, engine, native_engine,
                       schema, native_unify, merge_coplanar_angle, filename, stem,
                       n_in_tris, cut_before, cut_after, repair_info, feature=False) -> dict:
    """The part that takes minutes. Runs on a worker so the request can let go.

    Bounded by _CONVERT_SLOTS: measured on this host a 64k-triangle gate needs 91s
    alone, and the same work under load average 19 got 18% of a core and blew a
    900s ceiling. Queuing beats thrashing.
    """
    if not _CONVERT_SLOTS.acquire(timeout=QUEUE_WAIT_S):
        # Admission should make this unreachable -- MAX_ADMITTED_CONVERSIONS is
        # sized so the last waiter starts inside QUEUE_WAIT_S. If it ever fires
        # anyway it is still backpressure, not a server fault, so it answers 429
        # with a Retry-After like every other refusal.
        __import__("shutil").rmtree(workdir, ignore_errors=True)
        raise _busy(
            "The converter is busy with other models right now. "
            "Please try again in a minute — your file was not kept."
        )
    t_convert = time.time()
    try:
        try:
            res = convert_native(
                stl_path, out_path,
                engine=native_engine, schema=schema, unify_angle=native_unify,
                no_unify=(engine == "faceted" and merge_coplanar_angle is None),
                # the shorter engine cap only applies when the fallback can use the time it frees
                timeout=(min(NATIVE_TIMEOUT_S, CONVERT_TIMEOUT_S)
                         if engine == "trueform" and os.environ.get("MESH2STEP_ENGINE_FALLBACK") == "1"
                         else CONVERT_TIMEOUT_S),
            )
            if (engine == "trueform" and not res.get("ok")
                    and "post-write verification failed" in str(res.get("error") or "")):
                # the engine skipped zero-area triangles of a watertight mesh and wrote an open shell, which re-reads
                # as 0 solids (convogliatore auto rally v3 v5: 12 sliver triangles). Sewing every component first
                # closes it; served only if that build passes the engine's own verification
                sewn = convert_native(stl_path, out_path, engine=native_engine, schema=schema, unify_angle=native_unify,
                                      timeout=CONVERT_TIMEOUT_S, force_sew=True)
                if sewn.get("ok"):
                    sewn["warnings"] = [f"the first build did not re-read as a solid ({res.get('error')}); "
                                        "rebuilt with --force-sew", *(sewn.get("warnings") or [])]
                    res = sewn
        except NativeEngineError as e:          # NativeTimeout included
            # OPT-IN (MESH2STEP_ENGINE_FALLBACK=1): the documented contract is that a timeout answers 504 and explains
            # itself (test_a_timeout_explains_itself_and_cleans_up); serving a rebuilt shape instead changes that.
            if engine != "trueform" or os.environ.get("MESH2STEP_ENGINE_FALLBACK") != "1":
                raise
            # the engine hung or failed: the rebuild does not need its output, only the mesh. Served only if it passes
            # the same gate; otherwise the engine's error stands.
            res = _edgebuild_upgrade(stl_path, out_path, {
                "ok": True, "triangles": n_in_tris, "smoothBuiltCylinders": 0,
                "warnings": [f"the conversion engine did not finish ({type(e).__name__}); the shape was rebuilt without it"],
            })
            if res.get("featureMethod") != "edgebuild":
                raise
        if engine == "trueform" and res.get("ok") and not res.get("featureMethod"):
            res = _retry_broken_trueform(stl_path, out_path, res, schema=schema,
                                         unify_angle=native_unify)
            res = _edgebuild_upgrade(stl_path, out_path, res)
        if (engine == "trueform" and res.get("ok") and not res.get("featureMethod")
                and (feature or os.environ.get("MESH2STEP_FEATURE") == "1")):
            res = _feature_upgrade(stl_path, out_path) or res
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
        # The queue is sized on how long conversions ACTUALLY take here, not on
        # how long they took on the machine the constants were written on. A
        # timed-out or failed run counts too: it held the slot just the same.
        observe_convert_seconds(time.time() - t_convert)
    d = _native_stats(res, engine, schema)
    d["backend"] = "native"
    if res.get("featureMethod"):
        # a validated feature build: the post-passes below audit ENGINE output only
        d["backend"] = "feature"
        d["feature_method"] = res["featureMethod"]
    trueform_post = engine == "trueform" and "feature_method" not in d
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

    # Audit what the ENGINE already turned into cylinders. Its Phase-B seed band takes
    # any facet step in [5, 60] degrees, so a designed 8-sided prism comes back as its
    # circumscribed cylinder (+11.07%) with the facets gone from the STEP -- nothing
    # downstream can decline it, and the engine emits no warning of its own. Saying so,
    # with the numbers, is all this can do until the seeding itself is fixed
    # (.claude/loopspec/n5-seed-exclusion.spec.md).
    if trueform_post and d.get("smooth_cylinders", 0) > 0:
        try:
            from mesh2step.intent import audit_engine_cylinders

            rows = audit_engine_cylinders(stl_path, out_path)
            # every engine-rebuilt band is accounted for in the payload, flagged or not
            d["engine_cylinder_audit"] = [
                {"radius": round(r.radius, 4), "sides": r.sides,
                 "turn_deg": round(r.turn_deg, 3), "sagitta": round(r.sagitta, 6),
                 "model_tolerance": (round(r.model_tolerance, 6)
                                     if r.model_tolerance is not None else None),
                 "ratio": round(r.ratio, 3) if r.ratio is not None else None,
                 "volume_delta_pct": round(r.volume_delta_pct, 4),
                 "flagged": r.flagged, "undecidable": r.undecidable}
                for r in rows
            ]
            # a band nothing can decide is the one a person most needs to see
            for finding in rows:
                if not (finding.flagged or finding.undecidable):
                    continue
                if finding.message not in d.setdefault("warnings", []):
                    d["warnings"].append(finding.message)
        except Exception:  # noqa: BLE001 - a diagnostic must never fail a conversion
            pass

    # A volume move with no analytic rebuild behind it is a state-2 case: the geometry
    # is kept exactly as produced, and the user is told, with the numbers. Measured on
    # L07_flanged_bushing_recon -- 258 faces, all planes, against 32 non-planar truth
    # faces; 245 planes absorb facets deviating up to 1.99 deg against the engine's
    # absolute 2.0 deg near-flat gate; area barely moves, volume moves 1.70 %.
    if trueform_post and d["output_size_bytes"] <= CANONIZE_MAX_BYTES:
        try:
            from mesh2step.intent import unaccounted_volume_move

            vf = unaccounted_volume_move(stl_path, out_path, d)
            if vf is not None:
                d["volume_unaccounted_pct"] = round(vf.volume_delta_pct, 4)
                if vf.message not in d.setdefault("warnings", []):
                    d["warnings"].append(vf.message)

            # The SHAPE line beside the volume one: 12 of the 18 corpus models that
            # flatten curvature move the volume by ~0, so a volume test covers the harm
            # but not the phenomenon -- a conical seat as forty planes has the right
            # volume and the wrong shape.
            from mesh2step.intent import flattening_suspected

            ff = flattening_suspected(stl_path, out_path)
            if ff is not None:
                d["flattened_faces"] = ff.faces_absorbing
                if ff.message not in d.setdefault("warnings", []):
                    d["warnings"].append(ff.message)
        except Exception:  # noqa: BLE001 - a diagnostic must never fail a conversion
            pass

    # Recover the circles the engine's seed band missed. Default ON for trueform:
    # a rebuilt file is the geometry the facets were approximating, and it is
    # smaller (a real lid: 245 faces -> 10, 1.95 MB -> 33 KB). Accepted only if
    # the result is a valid solid, nothing failed, and the volume moved less than
    # 2% -- otherwise the original conversion is kept, silently and intact.
    if (trueform_post and d.get("smooth_cylinders", 0) == 0
            and d.get("smooth_planes", 0) > 12
            and d["output_size_bytes"] <= CANONIZE_MAX_BYTES):
        try:
            from mesh2step.rebuild import rebuild_cylinders

            rebuilt_path = workdir / "rebuilt.step"
            rb = rebuild_cylinders(out_path, rebuilt_path)
            # A band kept faceted on intent evidence is reported whether or not the
            # rebuild is then accepted: "kept faceted (designed prism?)" with the
            # numbers behind it is the actionable half, and it is true either way.
            for warning in rb.get("warnings", []):
                if warning not in d.setdefault("warnings", []):
                    d["warnings"].append(warning)
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
    if (trueform_post and not d.get("rebuilt")
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


def _convert_job(*, t_admit: float, **kw) -> dict:
    """Own the admission slot for the whole life of the conversion.

    The slot is taken in the request handler, before the upload is written, and
    must be given back exactly once however the work ends -- success, engine
    failure, timeout, or an exception nobody predicted. A leaked slot is
    permanent: the queue shrinks by one for the life of the process.
    """
    try:
        return _convert_in_worker(**kw)
    finally:
        _release_admission()
        # The service's OWN per-conversion cost: admission granted (before the
        # upload is even written) to result ready. The client's figure also
        # carries the upload, the poll interval and the download, so the two
        # are not the same number and only this one is a capacity gate.
        print(f"SRVCONV {time.time() - t_admit:.3f} tris={kw.get('n_in_tris')}",
              file=sys.stderr, flush=True)


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
    feature: bool = Form(False),
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

    admitted, wait_s = _try_admit()
    if not admitted:
        raise _busy(queue_full_message(wait_s), wait_s)
    t_admit = time.time()
    # Free space must cover this conversion AND every one already admitted, so
    # the check is made after taking the slot -- _admission_depth() includes us.
    if _disk_free_bytes() < _disk_headroom_bytes():
        _release_admission()
        raise _busy(DISK_FULL_MESSAGE)

    handed_off = False
    try:
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
        if n_in_tris > MAX_INPUT_TRIANGLES:
            __import__("shutil").rmtree(workdir, ignore_errors=True)
            raise HTTPException(413, (
                f"This model has {n_in_tris:,} triangles. The converter handles up to "
                f"{MAX_INPUT_TRIANGLES:,} — above that it needs more memory than the "
                "server can give it. Reduce the mesh (Simplify or Decimate in your "
                "CAD or slicer) and upload it again."
            ))
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
            _convert_job,
            t_admit=t_admit,
            stl_path=stl_path, out_path=out_path, workdir=workdir, engine=engine,
            native_engine=native_engine, schema=schema, native_unify=native_unify,
            merge_coplanar_angle=merge_coplanar_angle, filename=file.filename, stem=stem,
            n_in_tris=n_in_tris, cut_before=cut_before, cut_after=cut_after,
            repair_info=repair_info, feature=feature,
        )
        handed_off = True  # the worker owns the admission slot from here on
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
    finally:
        # Every path out of the block above that is not a hand-off -- a bad
        # mesh, an oversized model, a cut that removed everything, or a raise we
        # did not foresee -- gives the slot straight back.
        if not handed_off:
            _release_admission()



@app.get("/api/limits")
def limits() -> dict:
    """What the client should say before someone waits for a rejection."""
    return {"max_triangles": MAX_INPUT_TRIANGLES,
            "max_upload_mb": MAX_UPLOAD_BYTES // (1024 * 1024),
            "version": APP_VERSION}


@app.get("/api/job/{job}")
def job_status(job: str):
    entry = _PENDING.get(job)
    if entry is None:
        raise HTTPException(404, "unknown or expired job")
    fut = entry["future"]
    if not fut.done():
        return {"ok": True, "pending": True, "job": job,
                "elapsed": round(time.time() - entry["ts"], 1)}
    # kept until the TTL purge or the MAX_PENDING_JOBS cap: a client whose connection dropped
    # on the response carrying the result polls again and must get the same answer, not a 404
    try:
        return fut.result()
    except HTTPException as e:
        # headers carry the Retry-After a backpressure refusal is worthless without
        raise HTTPException(e.status_code, e.detail, headers=e.headers) from None



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



def _result_mesh(step_path: Path) -> dict:
    """The written STEP tessellated for the browser: every triangle tagged with the B-Rep face it
    came from, and every face with its surface type (and radius where it has one), so the page can
    show which faces were rebuilt as real geometry and which are still mesh facets."""
    import numpy as np
    from OCP import GeomAbs
    from OCP.Bnd import Bnd_Box
    from OCP.BRep import BRep_Tool
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepBndLib import BRepBndLib
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.STEPControl import STEPControl_Reader
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_REVERSED
    from OCP.TopExp import TopExp, TopExp_Explorer
    from OCP.TopLoc import TopLoc_Location
    from OCP.TopoDS import TopoDS
    from OCP.TopTools import TopTools_IndexedMapOfShape

    r = STEPControl_Reader()
    if r.ReadFile(str(step_path)) != 1:
        raise HTTPException(422, "the result could not be read back for preview")
    r.TransferRoots()
    shape = r.OneShape()
    box = Bnd_Box()
    BRepBndLib.Add_s(shape, box)
    x0, y0, z0, x1, y1, z1 = box.Get()
    diag = max(float(np.linalg.norm([x1 - x0, y1 - y0, z1 - z0])), 1e-6)
    BRepMesh_IncrementalMesh(shape, 1e-3 * diag, False, 0.35, True)
    kinds = {GeomAbs.GeomAbs_Plane: "plane", GeomAbs.GeomAbs_Cylinder: "cylinder",
             GeomAbs.GeomAbs_Cone: "cone", GeomAbs.GeomAbs_Sphere: "sphere",
             GeomAbs.GeomAbs_Torus: "torus"}
    pos, ids, faces = [], [], []
    ex = TopExp_Explorer(shape, TopAbs_FACE)
    while ex.More():
        f = TopoDS.Face_s(ex.Current())
        ex.Next()
        loc = TopLoc_Location()
        tri = BRep_Tool.Triangulation_s(f, loc)
        if tri is None:
            continue
        ad = BRepAdaptor_Surface(f)
        kind = kinds.get(ad.GetType(), "other")
        if kind == "plane":
            fe = TopTools_IndexedMapOfShape()
            TopExp.MapShapes_s(f, TopAbs_EDGE, fe)
            if fe.Extent() == 3:
                # ponytail: a triangular plane is a leftover mesh facet; a real triangular CAD face
                # would be mislabelled too, rare enough for a preview
                kind = "facet"
        face = {"type": kind}
        if kind == "cylinder":
            face["radius"] = round(ad.Cylinder().Radius(), 4)
        elif kind == "sphere":
            face["radius"] = round(ad.Sphere().Radius(), 4)
        tr = loc.Transformation()
        nodes = np.array([tri.Node(i).Transformed(tr).Coord() for i in range(1, tri.NbNodes() + 1)])
        tris = np.array([tri.Triangle(i).Get() for i in range(1, tri.NbTriangles() + 1)]) - 1
        if f.Orientation() == TopAbs_REVERSED:
            tris = tris[:, ::-1]
        pos.append(nodes[tris].reshape(-1, 3))
        ids.append(np.full(len(tris), len(faces), dtype=np.uint32))
        faces.append(face)
    positions = (np.concatenate(pos) if pos else np.zeros((0, 3))).astype(np.float32)
    face_ids = np.concatenate(ids) if ids else np.zeros(0, dtype=np.uint32)
    # every B-Rep edge as line segments: the face boundaries are what tells one clean plane from a
    # field of mesh facets, and shading alone hides it
    from itertools import pairwise

    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.GCPnts import GCPnts_QuasiUniformDeflection
    em = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_EDGE, em)
    segs = []
    for i in range(1, em.Extent() + 1):
        e = TopoDS.Edge_s(em.FindKey(i))
        if BRep_Tool.Degenerated_s(e):
            continue
        try:
            c = BRepAdaptor_Curve(e)
            d = GCPnts_QuasiUniformDeflection(c, 1e-3 * diag)
            pts = [d.Value(k).Coord() for k in range(1, d.NbPoints() + 1)] if d.IsDone() else []
        except Exception:  # noqa: BLE001 - one unsampleable edge must not cost the preview
            pts = []
        if len(pts) < 2:
            pts = [c.Value(c.FirstParameter()).Coord(), c.Value(c.LastParameter()).Coord()]
        segs.extend(pairwise(pts))
    edges = np.asarray(segs, dtype=np.float32).reshape(-1, 3)
    return {"positions": base64.b64encode(positions.tobytes()).decode(),
            "faceIds": base64.b64encode(face_ids.tobytes()).decode(),
            "edges": base64.b64encode(edges.tobytes()).decode(),
            "faces": faces}


@app.get("/api/result-mesh/{token}")
def result_mesh(token: str):
    job = _JOBS.get(token)
    if not job or not job["path"].exists():
        raise HTTPException(404, "result expired or not found")
    cache = job["path"].with_suffix(".preview3.json")   # v3: edges + facet faces
    if not cache.exists():
        cache.write_text(json.dumps(_result_mesh(job["path"])))
    return Response(cache.read_text(), media_type="application/json")


_GUIDE = Path(__file__).parent.parent / "docs" / "USER_GUIDE.md"


@app.get("/guide")
def guide():
    if not _GUIDE.exists():
        raise HTTPException(404, "guide not found")
    import markdown

    body = markdown.markdown(
        _GUIDE.read_text(encoding="utf-8"),
        extensions=["tables", "fenced_code"],
    )
    css = (
        ":root{color-scheme:dark}"
        "body{background:#111114;color:#e8e8ea;font:16px/1.65 system-ui,sans-serif;margin:0}"
        ".wrap{max-width:840px;margin:0 auto;padding:2rem 1.4rem 4rem}"
        ".top{display:flex;align-items:center;gap:.7rem;margin-bottom:1.2rem}"
        ".top img{height:34px}"
        ".top .name{font:700 1.3rem 'Chakra Petch',system-ui,sans-serif}"
        ".top .name span{color:#7dd87d}"
        ".top a.back{margin-left:auto;color:#9db4ff;font-size:.9rem}"
        "h1{font:700 2rem/1.2 'Chakra Petch',system-ui,sans-serif;margin:.2rem 0 1rem}"
        "h2{font-size:1.35rem;margin:2.2rem 0 .6rem;border-bottom:1px solid #333;padding-bottom:.3rem}"
        "h3{font-size:1.1rem;margin:1.6rem 0 .4rem}"
        "a{color:#9db4ff}"
        "table{border-collapse:collapse;width:100%;margin:1rem 0;font-size:.95rem}"
        "th{background:#1d1d22;text-align:left}"
        "th,td{border:1px solid #3a3a42;padding:.45rem .7rem;vertical-align:top}"
        "tbody tr:nth-child(even){background:#161619}"
        "pre{background:#0b0b0e;border:1px solid #2c2c33;border-radius:8px;padding:1rem;overflow-x:auto}"
        "code{font-size:.88em;background:#1d1d22;padding:.1em .35em;border-radius:4px}"
        "pre code{background:none;padding:0}"
        ".mermaid{display:flex;justify-content:center;background:#16161b;border:1px solid #2c2c33;"
        "border-radius:8px;padding:1rem}"
        "hr{border:none;border-top:1px solid #333;margin:2rem 0}"
        ".foot{margin-top:3rem;color:#888;font-size:.85rem}"
    )
    page = (
        "<!DOCTYPE html><html lang=\"en\"><head>"
        "<meta charset=\"UTF-8\" />"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />"
        "<title>mesh2step — user guide</title>"
        "<link rel=\"stylesheet\" href=\"https://fonts.googleapis.com/css2?family=Chakra+Petch:wght@600;700&display=swap\" />"
        "<style>" + css + "</style>"
        "</head><body><div class=\"wrap\">"
        "<div class=\"top\"><img src=\"assets/native-research.svg\" alt=\"Native Research\" />"
        "<span class=\"name\">mesh<span>2</span>step guide</span>"
        "<a class=\"back\" href=\"./\">&larr; Back to the app</a></div>"
        + body +
        "<p class=\"foot\">mesh2step by Native Research — uploads are deleted after an hour.</p>"
        "</div>"
        "<script src=\"https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js\"></script>"
        "<script>mermaid.initialize({startOnLoad:false,theme:'dark'});"
        "mermaid.run({querySelector:'code.language-mermaid'});</script>"
        "</body></html>"
    )
    return Response(page, media_type="text/html; charset=utf-8")


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
        "free_edges": res.get("freeEdges", 0),
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
                # what was BUILT, not what segmentation found: a reverted component finds
                # cylinders and ships none (Bracket_40: found 4, built 0)
                "smooth_built_planes": res.get("smoothBuiltPlanes"),
                "smooth_built_cylinders": res.get("smoothBuiltCylinders"),
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
