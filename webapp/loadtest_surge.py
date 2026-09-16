#!/usr/bin/env python3
"""Surge test for the LIVE mesh2step service: does the admission control hold?

Fires a burst of concurrent uploads at the URL given by --url (REQUIRED; use the
load-test twin, never the live unit), drains every job
ticket it gets back, and samples memory the whole time from three places at
once, because no single one of them is the answer:

  * /proc/<MainPID>/status VmRSS -- the uvicorn process only. The conversion
    engine is a CHILD process, so this number does NOT contain the conversion.
  * the service cgroup's memory.current / memory.peak -- process plus children,
    which is what MemoryMax=8G actually governs.
  * /proc/meminfo MemAvailable -- what is left for the rest of the machine.

Assertions, all of which must hold for the run to pass:
  * no OOM kill and no MemoryMax hit (cgroup memory.events max/oom_kill/oom
    counters must not move during the run);
  * no 5xx and no dropped connection;
  * every rejection is 429 and carries a Retry-After header;
  * cgroup peak stays under the stated bound;
  * the service answers a plain request after the burst.

Usage:  python3 webapp/loadtest_surge.py --url http://127.0.0.1:20007 [--burst 48]
Exit 0 = pass, 1 = assertion failed, 2 = could not run.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

# 2026-09-16: /tmp/awk is gone (tmp is cleared), so cadbench, sphere6 and mmx no
# longer exist and this harness could not run at all. The user corpus is a better
# mix anyway: 39 REAL mechanical parts, 1,784 to 166,372 triangles, with
# per-part conversion times measured on this very service the same night.
BENCH = Path("/home/tommaso/corpora/mechparts")
# The near-limit end of the mix. 25 and 33 sit just under the 120,000-triangle
# engine ceiling; 12 and 39 are ABOVE it and therefore exercise the oversize
# admission branch that sends them straight to the feature path -- a real
# surge will contain both kinds and they fail differently.
NEAR_LIMIT = [Path("/home/tommaso/corpora/mechparts/25.stl"),   # 107,608 tris
              Path("/home/tommaso/corpora/mechparts/33.stl"),   # 105,434 tris
              Path("/home/tommaso/corpora/mechparts/12.stl"),   # 164,996 tris, oversize
              Path("/home/tommaso/corpora/mechparts/39.stl")]   # 166,372 tris, oversize

# The unit the sampler watches. It must be the unit SERVING --url, or the memory
# numbers describe an idle process. Default is the load-test twin, for the same
# reason --url has no default.
# The load-test twin (mesh2step-loadtest, :20007) no longer exists -- neither the
# unit nor the port is present as of 2026-09-16. Rehearsing against the live unit
# is therefore the only option, and it is a deliberate choice made with the
# service idle, NOT a default: --url is still required and still has no default.
UNIT = "mesh2step"
SAMPLE_INTERVAL_S = 0.5
# 60-capacity.conf sets MemoryMax=24G against 6 slots (approved 2026-09-08 on
# twin evidence: six near-limit conversions peaked 4.68 GB in aggregate). The old
# 8G here was the pre-2026-09-08 ceiling and would fail a healthy run.
CGROUP_BOUND_BYTES = 24 * 1024**3
# The uvicorn process itself holds the loaded mesh and the framework -- AND, since
# MESH2STEP_FEATURE=1, the whole feature pass, which is Python running in-process
# rather than in the engine child. The old 2 GB assumed "the engine's gigabytes
# are in a child"; that stopped being the whole story when the feature path
# became the reason people use this service.
# Measured 2026-09-17, 48-request burst with 2 oversize feature conversions:
# server RSS peaked 3,261 MB while the cgroup peaked 6,534 MB and memory.events
# stayed all-zero (no throttle, no OOM). 6 GB is ~1.8x the observed peak: high
# enough not to fail a healthy run, low enough to catch a registry leak.
SERVER_RSS_BOUND_BYTES = 6 * 1024**3
JOB_POLL_TIMEOUT_S = 900.0   # matches CONVERT_TIMEOUT_S in server.py
JOB_POLL_INTERVAL_S = 3.0
REQUEST_TIMEOUT_S = 300.0
# The near-limit models are fired first and the small ones a second later. This
# is not to help them past admission -- it is the only ordering under which the
# memory bound is actually TESTED. Fired together, the heavy models lose the race
# for the two conversion slots to 45 small ones, get refused at the door, and the
# run reports a peak RSS that proves nothing. Heavy work already in flight when a
# surge lands is also the realistic bad case.
SURGE_HEAD_START_S = 1.0


# --------------------------------------------------------------------------- #
# sampling
# --------------------------------------------------------------------------- #
def _main_pid() -> int | None:
    env = dict(os.environ, XDG_RUNTIME_DIR=f"/run/user/{os.getuid()}")
    out = subprocess.run(["systemctl", "--user", "show", UNIT, "-p", "MainPID",
                          "--value"], capture_output=True, text=True, env=env)
    try:
        pid = int(out.stdout.strip())
    except ValueError:
        return None
    return pid or None


def _cgroup_dir(pid: int) -> Path | None:
    try:
        rel = Path("/proc") / str(pid) / "cgroup"
        line = rel.read_text().strip().split("\n")[0]
        return Path("/sys/fs/cgroup") / line.split(":")[-1].lstrip("/")
    except OSError:
        return None


def _read_int(path: Path) -> int | None:
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return None


def _mem_events(cg: Path | None) -> dict:
    if cg is None:
        return {}
    try:
        return {k: int(v) for k, v in
                (ln.split() for ln in (cg / "memory.events").read_text().splitlines())}
    except OSError:
        return {}


def _rss_bytes(pid: int) -> int | None:
    try:
        m = re.search(r"^VmRSS:\s+(\d+) kB", Path(f"/proc/{pid}/status").read_text(),
                      re.M)
        return int(m.group(1)) * 1024 if m else None
    except OSError:
        return None


def _mem_available_bytes() -> int:
    m = re.search(r"^MemAvailable:\s+(\d+) kB", Path("/proc/meminfo").read_text(), re.M)
    return int(m.group(1)) * 1024


class Sampler(threading.Thread):
    def __init__(self, pid: int, cg: Path | None):
        super().__init__(daemon=True)
        self.pid, self.cg = pid, cg
        self.stop_evt = threading.Event()
        self.samples: list[dict] = []
        self.restarted = False

    def run(self) -> None:
        while not self.stop_evt.is_set():
            rss = _rss_bytes(self.pid)
            if rss is None:                      # the process we were watching is gone
                new = _main_pid()
                if new and new != self.pid:      # ...and systemd replaced it: a restart
                    self.restarted = True
                    self.pid, self.cg = new, _cgroup_dir(new)
                    rss = _rss_bytes(self.pid)
            self.samples.append({
                "t": time.time(),
                "rss": rss,
                "cgroup": _read_int(self.cg / "memory.current") if self.cg else None,
                "avail": _mem_available_bytes(),
            })
            self.stop_evt.wait(SAMPLE_INTERVAL_S)


# --------------------------------------------------------------------------- #
# load
# --------------------------------------------------------------------------- #
def build_mix(burst: int) -> list[tuple[Path, str]]:
    """(file, engine) pairs: bench meshes on the default engine, plus the heavy two.

    The bench corpus runs on `faceted`, which is what the client actually sends
    by default. That is a fixture choice, not a softened assertion, and it is
    measured: NEG_DIN41612_C_3x32_Male_Horizontal_THT_normal.stl (19,042 tris) on
    `trueform` ran past CONVERT_TIMEOUT_S = 900s on this host at load average ~20
    and came back 504. That is the engine's speed on one awkward model -- a
    per-model verdict this test has no business measuring and no power to fix,
    since the engine and its timeout are fixed. Admission control is what is
    under test, so the mix must be models the engine can convert.

    The two near-limit models are on `trueform` precisely BECAUSE it is the heavy
    path, and both were timed through the live service on their own first:
    sphere6.stl (81,920 tris) 152s, mmx.stl (64,288 tris) 91s -- comfortably
    inside the timeout, so a 5xx from either is a real failure, not a fixture.
    """
    # NEAR_LIMIT now lives INSIDE BENCH (the old layout had it outside), so it
    # must be excluded from the filler pool or the heavy models get drawn twice.
    # The second draw is the damaging one: it would be sent on `faceted`, and
    # parts above MAX_INPUT_TRIANGLES = 120,000 are REFUSED 413 on that path.
    # The test would then record fixture-caused refusals as admission-control
    # behaviour, which is precisely the distinction it exists to make.
    # ...and exclude oversize by PROPERTY, not by name. Hand-listing NEAR_LIMIT
    # was not enough: mechparts/23 is 148,822 triangles, above the ceiling but
    # not in that list, so it landed in the faceted pool and would have been
    # refused 413 -- a fixture artefact scored as admission behaviour.
    def _tris(p: Path) -> int:
        with open(p, "rb") as fh:               # binary STL header count
            fh.seek(80)
            return int.from_bytes(fh.read(4), "little")

    _heavy = {f.resolve() for f in NEAR_LIMIT}
    small = sorted(p for p in BENCH.glob("*.stl")
                   if p.resolve() not in _heavy and _tris(p) <= 120_000)
    if not small:
        sys.exit(f"no bench meshes under {BENCH}")
    small.sort(key=lambda p: p.stat().st_size)
    mix: list[tuple[Path, str]] = []
    for f in NEAR_LIMIT:
        if f.exists():
            mix.append((f, "trueform"))          # the memory-heavy path
    # spread the rest across the corpus so the sizes are not all identical
    rest = burst - len(mix)
    step = max(1, len(small) // max(rest, 1))
    for i in range(rest):
        mix.append((small[(i * step) % len(small)], "faceted"))
    return mix[:burst]


def fire(url: str, path: Path, engine: str, delay: float = 0.0) -> dict:
    if delay:
        time.sleep(delay)
    t0 = time.time()
    rec = {"file": path.name, "bytes": path.stat().st_size, "engine": engine,
           "near_limit": path in NEAR_LIMIT}
    try:
        with path.open("rb") as fh:
            r = requests.post(f"{url}/api/convert",
                              files={"file": (path.name, fh, "application/octet-stream")},
                              data={"engine": engine},
                              timeout=REQUEST_TIMEOUT_S)
        rec["status"] = r.status_code
        rec["retry_after"] = r.headers.get("Retry-After")
        try:
            body = r.json()
        except ValueError:
            body = {}
        rec["detail"] = (body.get("detail") or "")[:160]
        rec["job"] = body.get("job")
        rec["pending"] = bool(body.get("pending"))
        rec["download_token"] = body.get("download_token")
    except requests.RequestException as e:
        rec["status"] = None
        rec["error"] = f"{type(e).__name__}: {e}"
    rec["latency"] = round(time.time() - t0, 3)
    return rec


def drain(url: str, records: list[dict]) -> list[dict]:
    """Poll every job ticket to a terminal answer; record how it ended."""
    outcomes = []
    live = [r for r in records if r.get("job")]
    deadline = time.time() + JOB_POLL_TIMEOUT_S
    while live and time.time() < deadline:
        still = []
        for rec in live:
            try:
                r = requests.get(f"{url}/api/job/{rec['job']}", timeout=60)
            except requests.RequestException as e:
                outcomes.append({"job": rec["job"], "status": None,
                                 "error": f"{type(e).__name__}: {e}"})
                continue
            body = {}
            try:
                body = r.json()
            except ValueError:
                pass
            if r.status_code == 200 and body.get("pending"):
                still.append(rec)
                continue
            outcomes.append({"job": rec["job"], "file": rec["file"],
                             "status": r.status_code,
                             "ok": bool(body.get("ok")),
                             "detail": (body.get("detail") or "")[:160]})
        live = still
        if live:
            time.sleep(JOB_POLL_INTERVAL_S)
    for rec in live:
        outcomes.append({"job": rec["job"], "file": rec["file"], "status": "TIMEOUT"})
    return outcomes


def pct(values: list[float], p: float) -> float:
    if not values:
        return float("nan")
    s = sorted(values)
    return s[min(len(s) - 1, int(round((p / 100) * (len(s) - 1))))]


def main() -> int:
    global UNIT
    ap = argparse.ArgumentParser()
    # NO DEFAULT, deliberately. This script previously defaulted to :8000 -- the LIVE unit,
    # which real traffic may hit. A load test must name its target explicitly, and the
    # target must be the load-test twin (mesh2step-loadtest.service, port claimed from the
    # majordomo pool), never production. Refusing to guess is the guard.
    ap.add_argument("--url", required=True,
                    help="target base URL, e.g. http://127.0.0.1:20007 (the loadtest twin). "
                         "Never point this at the live unit.")
    ap.add_argument("--burst", type=int, default=48)
    ap.add_argument("--json", default="/tmp/mesh2step_loadtest.json")
    ap.add_argument("--unit", default=UNIT,
                    help="systemd --user unit serving --url; the memory samples "
                         "come from ITS pid and cgroup, so it must match")
    args = ap.parse_args()

    UNIT = args.unit   # `global UNIT` is declared at the top of main()

    pid = _main_pid()
    if not pid:
        print(f"FATAL: {UNIT} has no MainPID -- is it running?")
        return 2
    cg = _cgroup_dir(pid)
    events_before = _mem_events(cg)
    mem_max = _read_int(cg / "memory.max") if cg else None
    print(f"service pid={pid} cgroup={cg} memory.max={mem_max} "
          f"events_before={events_before}")

    # baseline health, before we touch anything
    pre = requests.get(f"{args.url}/api/limits", timeout=30)
    print(f"pre-burst /api/limits -> {pre.status_code} {pre.text.strip()}")

    mix = build_mix(args.burst)
    print(f"burst={len(mix)} files, "
          f"{sum(b for _, b in ((f, f.stat().st_size) for f, _ in mix)) / 2**20:.1f} MB total, "
          f"largest {max(f.stat().st_size for f, _ in mix) / 2**20:.2f} MB")

    sampler = Sampler(pid, cg)
    sampler.start()
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=len(mix)) as ex:
        records = list(ex.map(
            lambda fe: fire(args.url, fe[0], fe[1],
                            0.0 if fe[0] in NEAR_LIMIT else SURGE_HEAD_START_S),
            mix))
    burst_s = time.time() - t0
    print(f"burst returned in {burst_s:.1f}s; draining job tickets...")
    outcomes = drain(args.url, records)
    sampler.stop_evt.set()
    sampler.join(timeout=5)
    total_s = time.time() - t0

    events_after = _mem_events(cg)
    peak = _read_int(cg / "memory.peak") if cg else None
    post = None
    try:
        post = requests.get(f"{args.url}/api/limits", timeout=30)
    except requests.RequestException as e:
        print(f"post-burst health check FAILED: {e}")

    rss = [s["rss"] for s in sampler.samples if s["rss"]]
    cgm = [s["cgroup"] for s in sampler.samples if s["cgroup"]]
    avail = [s["avail"] for s in sampler.samples if s["avail"]]
    lat = [r["latency"] for r in records]

    dist: dict[str, int] = {}
    for r in records:
        key = str(r.get("status"))
        dist[key] = dist.get(key, 0) + 1

    print("\n=== burst =========================================================")
    print(f"requests           {len(records)}   wall {burst_s:.1f}s   total {total_s:.1f}s")
    print(f"status distribution {dist}")
    print(f"latency  p50 {pct(lat,50):.2f}s   p90 {pct(lat,90):.2f}s   "
          f"max {max(lat):.2f}s")
    print("=== memory ========================================================")
    print(f"samples            {len(sampler.samples)} @ {SAMPLE_INTERVAL_S}s")
    if rss:
        print(f"server RSS         peak {max(rss)/2**20:8.1f} MB  "
              f"(bound {SERVER_RSS_BOUND_BYTES/2**20:.0f} MB)")
    if cgm:
        print(f"cgroup current     peak {max(cgm)/2**20:8.1f} MB  "
              f"(bound {CGROUP_BOUND_BYTES/2**20:.0f} MB)")
    if peak:
        print(f"cgroup memory.peak      {peak/2**20:8.1f} MB  (high-water, whole unit life)")
    if avail:
        print(f"MemAvailable       min  {min(avail)/2**30:8.2f} GB")
    print(f"memory.events after {events_after}")
    print("=== jobs ==========================================================")
    jd: dict[str, int] = {}
    for o in outcomes:
        jd[str(o.get("status"))] = jd.get(str(o.get("status")), 0) + 1
    print(f"job tickets issued {len(outcomes)}  outcomes {jd}")

    # ---------------- assertions ----------------
    failures: list[str] = []

    for k in ("max", "oom", "oom_kill"):
        if events_after.get(k, 0) > events_before.get(k, 0):
            failures.append(f"cgroup memory.events[{k}] rose "
                            f"{events_before.get(k,0)} -> {events_after.get(k,0)}")
    if sampler.restarted:
        failures.append("the service MainPID changed during the run (it restarted)")

    five_xx = [r for r in records if isinstance(r.get("status"), int)
               and 500 <= r["status"] < 600]
    if five_xx:
        failures.append(f"{len(five_xx)} request(s) got 5xx: "
                        f"{[(r['file'], r['status'], r['detail']) for r in five_xx][:4]}")
    job_5xx = [o for o in outcomes if isinstance(o.get("status"), int)
               and 500 <= o["status"] < 600]
    if job_5xx:
        failures.append(f"{len(job_5xx)} job(s) ended 5xx: {job_5xx[:4]}")

    dropped = [r for r in records if r.get("status") is None]
    if dropped:
        failures.append(f"{len(dropped)} request(s) never got a response: "
                        f"{[r.get('error') for r in dropped][:4]}")

    for r in records:
        if r.get("status") == 429 and not r.get("retry_after"):
            failures.append(f"429 without Retry-After: {r['file']}")
        if isinstance(r.get("status"), int) and r["status"] in (503,):
            failures.append(f"queue rejection came back as 503, not 429: {r['file']}")

    if rss and max(rss) > SERVER_RSS_BOUND_BYTES:
        failures.append(f"server RSS {max(rss)/2**20:.0f} MB exceeded bound "
                        f"{SERVER_RSS_BOUND_BYTES/2**20:.0f} MB")
    if cgm and max(cgm) > CGROUP_BOUND_BYTES:
        failures.append(f"cgroup memory {max(cgm)/2**20:.0f} MB exceeded bound "
                        f"{CGROUP_BOUND_BYTES/2**20:.0f} MB")

    if post is None or post.status_code != 200:
        failures.append("service did not answer /api/limits after the burst")

    served_near_limit = [r for r in records if r.get("near_limit")
                         and r.get("status") == 200]
    if NEAR_LIMIT and not served_near_limit:
        failures.append("no near-limit model was accepted, so the memory bound "
                        "was never exercised -- the RSS numbers prove nothing")

    stuck = [o for o in outcomes if o.get("status") == "TIMEOUT"]
    if stuck:
        failures.append(f"{len(stuck)} job(s) never reached a terminal state")

    Path(args.json).write_text(json.dumps(
        {"records": records, "outcomes": outcomes, "dist": dist,
         "latency_p50": pct(lat, 50), "latency_p90": pct(lat, 90),
         "latency_max": max(lat) if lat else None,
         "rss_peak": max(rss) if rss else None,
         "cgroup_peak_sampled": max(cgm) if cgm else None,
         "cgroup_memory_peak": peak,
         "mem_available_min": min(avail) if avail else None,
         "events_before": events_before, "events_after": events_after,
         "post_health": post.status_code if post is not None else None,
         "failures": failures}, indent=2))

    print("=== verdict =======================================================")
    if failures:
        for f in failures:
            print(f"FAIL: {f}")
        return 1
    print(f"PASS: no OOM, no 5xx, every rejection a 429 with Retry-After, "
          f"service answering ({post.status_code}). Detail in {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
