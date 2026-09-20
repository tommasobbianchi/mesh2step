#!/usr/bin/env python3
"""Two-arm bench for the feature-pass agent loop, off the live service.

Arm `off` is `MESH2STEP_LOOP=0`: the one-shot pass exactly as `main` ships it. Arm `on` is the
repair loop. Both arms run from THIS worktree, share one engine STEP per part (the engine is
deterministic and unmodified, and running it twice would only add minutes), and are scored by
the same instrument the corpus baseline used -- `scripts/patch_representation.py:represent`,
centroid sampling, analytic quadrics only -- plus the raw ISO-10303 text census as an
independent witness.

A part whose feature pass produces nothing DELIVERS THE ENGINE STEP, which is what the service
does, so the score is the score of the file a user would download. A timeout is a failure and is
reported as one (guideline 2.2); it is never left out of the denominator.

usage: agent_loop_bench.py --parts 16 19 6 33 --arms off on --out bench.tsv [--jobs 4]
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

NATIVE = os.environ.get("MESH2STEP_NATIVE",
                        "/home/tommaso/projects/mesh2step/refs/stl2step/RUN.sh")


def engine_step(stl: Path, out: Path, timeout: float) -> bool:
    if out.exists():
        return True
    cmd = [NATIVE, str(stl), "-o", str(out), "--engine", "trueform", "--schema", "ap214",
           "--quiet"]
    try:
        subprocess.run(cmd, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False
    return out.exists()


def feature_pass(stl: Path, eng: Path, out: Path, logf: Path, loop: bool,
                 timeout: float) -> tuple[str, float]:
    """('feature'|'native'|'TIMEOUT', seconds). Writes the DELIVERED step to `out`."""
    t0 = time.time()
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"),
               MESH2STEP_NATIVE=NATIVE, MESH2STEP_LOOP="1" if loop else "0")
    cand = out.with_suffix(".cand.step")
    try:
        p = subprocess.run([sys.executable, "-m", "mesh2step.feature", str(stl), "-o", str(cand),
                            "--no-fallback", "--engine-step", str(eng)],
                           capture_output=True, text=True, timeout=timeout, env=env,
                           start_new_session=True)
    except subprocess.TimeoutExpired as e:
        logf.write_text((e.stderr or b"").decode("utf-8", "replace") if e.stderr else "")
        shutil.copyfile(eng, out)
        return "TIMEOUT", time.time() - t0
    logf.write_text((p.stderr or "") + (p.stdout or ""))
    if p.returncode == 0 and cand.exists():
        shutil.copyfile(cand, out)
        return "feature", time.time() - t0
    shutil.copyfile(eng, out)
    return "native", time.time() - t0


def score(stl: Path, step: Path) -> dict:
    from patch_representation import represent, step_entity_census

    r = represent(stl, step)
    ents = step_entity_census(step.read_bytes())
    r["cyl_ents"] = ents["CYLINDRICAL_SURFACE"]
    r["tor_ents"] = ents["TOROIDAL_SURFACE"]
    r.pop("diag", None)
    return r


def method_of(log: Path) -> str:
    """The method that actually WON, from the RESULT line -- not the last ACCEPT.

    Several candidates can qualify and the survivor is chosen by volume proximity, so reading
    the log's last acceptance names the wrong build (part 8: `block` accepted last, `stepped`
    delivered).
    """
    import json
    for ln in reversed(log.read_text().splitlines()):
        if ln.startswith("RESULT "):
            return json.loads(ln[7:]).get("featureMethod", "")
    return ""


def run_part(part: str, stl: Path, wd: Path, arms: list[str], timeout: float,
             engine_arm: bool = True) -> list[dict]:
    rows = []
    eng = wd / f"{part}.engine.step"
    if not engine_step(stl, eng, timeout):
        return [{"part": part, "arm": a, "status": "ENGINE_FAIL"} for a in arms]
    if engine_arm:
        # Scoring the engine's own STEP costs a BRepExtrema query against a compound of every
        # facet in the part. On a 100k-triangle mesh that file is 200 MB and the scoring, not the
        # conversion, becomes the run's tail -- so it is optional.
        rows.append(dict(score(stl, eng), part=part, arm="engine", backend="native", method="",
                         s=0.0, status="OK"))
    for arm in arms:
        out = wd / f"{part}.{arm}.step"
        log = wd / f"{part}.{arm}.log"
        backend, secs = feature_pass(stl, eng, out, log, arm == "on", timeout)
        try:
            r = score(stl, out)
            st = "OK" if backend != "TIMEOUT" else "TIMEOUT"
        except Exception as e:  # noqa: BLE001
            r, st = {}, f"SCOREERR:{type(e).__name__}"
        rows.append(dict(r, part=part, arm=arm, backend=backend, method=method_of(log),
                         s=round(secs, 1), status=st))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parts", nargs="+", required=True)
    ap.add_argument("--arms", nargs="+", default=["off", "on"])
    ap.add_argument("--dir", default="~/corpora/mechparts")
    ap.add_argument("--workdir", default="/tmp/agent_loop_bench")
    ap.add_argument("--out", default="agent_loop_bench.tsv")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--timeout", type=float, default=3600.0)
    ap.add_argument("--no-engine-arm", action="store_true")
    a = ap.parse_args()

    src = Path(a.dir).expanduser()
    wd = Path(a.workdir).expanduser()
    wd.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    with cf.ProcessPoolExecutor(max_workers=a.jobs) as ex:
        futs = {ex.submit(run_part, p, src / f"{p}.stl", wd, a.arms, a.timeout,
                          not a.no_engine_arm): p
                for p in a.parts}
        for f in cf.as_completed(futs):
            for r in f.result():
                rows.append(r)
                print(f"  {r['part']:>4} {r['arm']:<7} {r.get('backend',''):<8} "
                      f"{r.get('method',''):<22} patches={r.get('patches','-'):>4} "
                      f"curved={r.get('curved','-'):>4} plane={r.get('plane','-'):>4} "
                      f"far={r.get('far','-'):>3} cyl_ents={r.get('cyl_ents','-'):>4} "
                      f"{r['status']} {r.get('s','')}s", flush=True)

    cols = ["part", "arm", "backend", "method", "patches", "curved", "plane", "other", "far",
            "cyl_ents", "tor_ents", "status", "s"]
    Path(a.out).write_text("\t".join(cols) + "\n" + "\n".join(
        "\t".join(str(r.get(c, "")) for c in cols)
        for r in sorted(rows, key=lambda r: (r["part"], r["arm"]))) + "\n")
    print(f"\nwrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
