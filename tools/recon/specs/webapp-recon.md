# webapp-recon — run the AI rebuild after each conversion, as an additional result

## Context
`tools/recon/recon_part.py <stl> <workdir> --models M1 [M2 ...] --rounds N --timeout S` reconstructs
an uploaded mesh with a model cascade and writes `<workdir>/recon_result.json` (keys: `status`
accepted|best_effort|failed|unavailable, `model`, `best_step`, `report`, `represent`, `seconds`).
Put it in front of users WITHOUT touching the existing conversion: the pipeline result is served
exactly as today; the AI rebuild is queued afterwards and offered as a second download.

## Change ONLY `webapp/server.py`. Do not edit tests. No new dependencies.

## Required behaviour (acceptance test: `tests/test_webapp_recon.py` — read it first)
1. Config, read at call time (not import time) so tests can set them: `MESH2STEP_RECON` ("1" =
   enabled; default off), `MESH2STEP_RECON_MODELS` (space-separated, default "opus"),
   `MESH2STEP_RECON_ROUNDS` (default 5), `MESH2STEP_RECON_TIMEOUT_S` (default 2700).
2. Module-level `_run_recon(stl_path: Path, workdir: Path) -> dict`: run
   `[sys.executable, <repo>/tools/recon/recon_part.py, str(stl_path), str(workdir), "--models", *models,
   "--rounds", rounds, "--timeout", timeout]` with a subprocess timeout of timeout + 300 s, then return
   the parsed `workdir/recon_result.json`; if it is missing return `{"status": "failed"}`.
   Tests replace this function with monkeypatch, so call it through the module (`_run_recon(...)`
   looked up at call time), never through a captured reference.
3. `_RECON: dict[str, dict]` keyed by the conversion's download token, and
   `_RECON_POOL = ThreadPoolExecutor(max_workers=1)` (one rebuild at a time).
4. At the very end of `_convert_in_worker`, after `_JOBS[token] = ...` is set and before returning,
   if enabled: set `_RECON[token] = {"status": "queued", "ts": time.time()}` and submit a worker that
   - sets status "running";
   - calls `_run_recon(stl_path, workdir / "recon")` (stl_path = the conversion's input STL);
   - on a result with a `best_step` that exists: registers it as a new download
     `_JOBS[rtok] = {"path": Path(best_step), "name": f"{stem}.ai.step", "ts": time.time()}` and stores
     `_RECON[token] = {"status": res["status"], "model": res.get("model"), "seconds": res.get("seconds"),
     "download_token": rtok, "metrics": {valid, faces, cylinders, cones, tori, planes, bsplines,
     p95 (= max of the two p95), curved, patches}}` (from `report`/`represent`, missing keys -> None);
   - on any exception, or a result without a usable `best_step`: `_RECON[token] = {"status":
     res.get("status", "failed") if it is "unavailable" else "failed", "error": str(exc)[:300] if any}`;
   - prints one stderr line: `SRVRECON <seconds> status=<s> model=<m> faces=<f> curved=<c>/<p> p95=<e>`.
   The worker must never raise into the pool and must never modify the original conversion's entry.
   The whole hook is wrapped so that an exception in queueing can never fail the conversion.
5. `GET /api/recon/{token}`: if not enabled -> `{"status": "disabled"}` (200); enabled and unknown
   token -> 404; else the `_RECON[token]` dict (without the `ts` key).
6. When a conversion's `_JOBS` entry is dropped (`_drop_job`), also drop `_RECON[token]` (the rebuild's
   own `_JOBS` entry expires by the normal TTL/cap rules).

## Check
`cd /home/tommaso/projects/mesh2step && timeout 900 python3 -m pytest -q tests/test_webapp_recon.py tests/test_webapp_api.py tests/test_webapp_engine_fallback.py`
