"""Fleet runner: the engine corpus (tools/engine/run.py) across nativedev + Tailscale hosts.

usage: fleet.py <run> [--commit HEAD] [--parts 1,2,7] [--hosts nativedev,behemoth,beast,fujiyama1,fujiyama]
                [--slots behemoth=2,beast=1] [--timeout 1500] [--setup-only]

Run it under watchjob, e.g.
  ~/.claude/skills/watchjob/scripts/watchjob.sh engine-fleet-v2 -- \
    'cd <worktree> && python3 tools/engine/fleet.py corpus_v2 > runs/engine/corpus_v2.fleet.log 2>&1'

What it does:
  1. freezes `git archive <commit> tools` once into ~/engine-fleet/<run>/ on nativedev, plus the inputs
     (mechparts/<n>.stl, evidence runs/engine/steps/<n>.step, fallback steps_quick/<n>.step);
  2. per remote host builds ~/engine-fleet/venv (uv-managed CPython of nativedev's major.minor, every
     package in the closure of ENV_ROOTS pinned to nativedev's installed version; reused when versions
     match) and rsyncs the stage to ~/engine-fleet/<run>/; nativedev itself runs on its system python3;
  3. one worker per host (slots = max(1, nproc // 4), override with --slots) under watchjob, unit
     claudejob-fleet-<run>-<host>; the queue stays here: parts go out largest STL first, one at a time,
     to whichever host has a free slot (work stealing), and a host whose worker dies has its parts requeued;
  4. pulls <n>.json / <n>.log / <n>.time back into runs/engine/<run>/ as each part finishes;
  5. prints a per-host / per-part summary and runs compare.py on the output dir.
Unreachable hosts, hosts whose env cannot be built, and hosts without `loginctl enable-linger` (the user
manager would SIGKILL the worker when the last ssh session closes) are skipped with a message; they never block.
Smoke 2026-09-26 (parts 7,4,8 @ 0646658): behemoth, native-beast, fujiyama-1 each gave merit, steps and tree
JSON identical to a local nativedev run. Hosts: behemoth 16 cores, fujiyama-1 12, native-beast 4.
Stdlib only, plus ssh / rsync / git / uv.
"""
import argparse
import importlib.metadata as md
import json
import re
import shlex
import subprocess
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MECH = Path("/home/tommaso/corpora/mechparts")
EVID = [REPO / "runs/engine/steps", REPO / "runs/engine/steps_quick"]
HOSTS = {"nativedev": None, "behemoth": "tommaso@100.103.234.2", "beast": "tommaso@100.115.135.14",
         "fujiyama1": "tommaso@100.85.88.58", "fujiyama": "tommaso@100.71.227.80"}
FLEET = "engine-fleet"                                  # ~/engine-fleet on every host
WATCHJOB = Path.home() / ".claude/skills/watchjob/scripts/watchjob.sh"
JOB = Path.home() / ".claude/scripts/job"
UV = Path.home() / ".local/bin/uv"
ENV_ROOTS = ["cadquery", "cadquery-ocp", "shapely", "trimesh", "scipy", "numpy",
             "networkx", "rtree", "manifold3d", "lxml"]   # the last two: trimesh booleans and 3MF/XML, imported at run time
CHECK = "import OCP, shapely, trimesh, scipy, numpy, cadquery, manifold3d, rtree, networkx"

WORKER = r'''
import json, os, subprocess, sys, threading, time
stage, slots, py, threads, tmo = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4], sys.argv[5]
os.chdir(stage)
env = dict(os.environ, OMP_NUM_THREADS=threads, OPENBLAS_NUM_THREADS=threads, MKL_NUM_THREADS=threads)
def take():
    for n in sorted(os.listdir("q/inbox")):
        try:
            os.rename("q/inbox/" + n, "q/running/" + n)      # atomic claim among this host's slots
            return n
        except FileNotFoundError:
            pass
def slot():
    while True:
        n = take()
        if n is None:
            if os.path.exists("q/STOP"):
                return
            time.sleep(2); continue
        t0 = time.time()
        with open(f"out/{n}.log", "w") as log:
            rc = subprocess.call(["timeout", tmo, py, "tools/engine/run.py", f"in/{n}.stl", f"in/{n}.step",
                                  f"out/{n}.json"], stdout=log, stderr=subprocess.STDOUT, env=env)
        json.dump({"rc": rc, "seconds": round(time.time() - t0, 1)}, open(f"out/{n}.time", "w"))
        os.rename("q/running/" + n, "q/done/" + n)
ts = [threading.Thread(target=slot) for _ in range(slots)]
[t.start() for t in ts]; [t.join() for t in ts]
'''


def sh(host, cmd, timeout=60, check=False):
    """Run a shell command on host (None = here); returns CompletedProcess with text stdout."""
    argv = ["bash", "-c", cmd] if host is None else \
        ["ssh", "-o", "ConnectTimeout=8", "-o", "BatchMode=yes", host, cmd]
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        r = subprocess.CompletedProcess(argv, 124, e.stdout or "", "timeout")
    if check and r.returncode:
        raise RuntimeError(f"{host or 'local'}: {cmd[:80]}... rc={r.returncode}: {(r.stderr or '')[-400:]}")
    return r


def pins():
    """Every distribution in the closure of ENV_ROOTS, pinned to the version installed here."""
    out, todo = {}, list(ENV_ROOTS)
    while todo:
        name = re.sub(r"[-_.]+", "-", todo.pop()).lower()
        if name in out:
            continue
        try:
            d = md.distribution(name)
        except md.PackageNotFoundError:
            continue
        out[name] = d.version
        for req in d.requires or []:
            if "extra ==" in req:
                continue
            todo.append(re.match(r"[A-Za-z0-9_.\-]+", req).group(0))
    return out


def versions_cmd(py):
    names = json.dumps(sorted(pins()))
    return (f"{py} -c 'import importlib.metadata as m, json; "
            f"print(json.dumps({{n: m.version(n) for n in {names}}}))' 2>/dev/null")


class Host:
    def __init__(self, name, ssh):
        self.name, self.ssh, self.ok, self.note = name, ssh, False, ""
        self.nproc = self.slots = 0
        self.env_built = "n/a"
        self.py = sys.executable
        self.home = None
        self.out = set()                                # parts assigned and not yet pulled
        self.done = []                                  # (part, seconds, rc)
        self.proc = None
        self.job = None

    def stage(self, run):
        return f"{self.home}/{FLEET}/{run}"


def setup_host(h, run, local_stage, pinned, slots_override):
    r = sh(h.ssh, "nproc; echo $HOME", timeout=20)
    if r.returncode:
        h.note = "unreachable"
        return
    h.nproc, h.home = int(r.stdout.split()[0]), r.stdout.split()[1]
    if h.ssh is not None and "Linger=yes" not in sh(h.ssh, "loginctl show-user $(id -un) -p Linger").stdout:
        # without linger the user manager exits with the last ssh session and SIGKILLs the watchjob unit
        # (seen on native-beast 2026-09-26); fix once on the host with `loginctl enable-linger`
        h.note = "systemd --user linger is off (run `loginctl enable-linger` there)"
        return
    h.slots = slots_override.get(h.name, max(1, h.nproc // 4))
    if h.ssh is not None:
        venv = f"{h.home}/{FLEET}/venv"
        h.py = f"{venv}/bin/python"
        have = sh(h.ssh, versions_cmd(h.py) + f" && {h.py} -c '{CHECK}'", timeout=120)
        want = dict(pinned)
        if have.returncode == 0 and json.loads(have.stdout.strip().splitlines()[0]) == want:
            h.env_built = "reused"
        else:
            pyver = "%d.%d" % sys.version_info[:2]
            spec = shlex.quote("\n".join(f"{k}=={v}" for k, v in sorted(want.items())))
            try:
                sh(h.ssh, f"mkdir -p {h.home}/{FLEET}/bin", check=True)
                subprocess.run(["rsync", "-a", str(UV), f"{h.ssh}:{h.home}/{FLEET}/bin/uv"], check=True,
                               capture_output=True, timeout=300)
                uv = f"{h.home}/{FLEET}/bin/uv"
                # sync = exactly the pinned closure, nothing else (cadquery-ocp-novtk beside cadquery-ocp
                # overwrites OCP/ with a build lacking IVtkOCC_Shape, so extraneous packages must go)
                sh(h.ssh, f"{uv} venv --allow-existing --python {pyver} {venv} && "
                          f"printf '%s\\n' {spec} > {h.home}/{FLEET}/req.txt && "
                          f"{uv} pip sync --python {h.py} --reinstall-package cadquery-ocp {h.home}/{FLEET}/req.txt",
                   timeout=1800, check=True)
                have = sh(h.ssh, versions_cmd(h.py) + f" && {h.py} -c '{CHECK}'", timeout=300)
                if have.returncode or json.loads(have.stdout.strip().splitlines()[0]) != want:
                    raise RuntimeError("versions still differ after install")
                h.env_built = "built"
            except Exception as e:                      # noqa: BLE001 -- a host that cannot get the env is skipped
                h.note = f"env failed: {str(e)[-300:]}"
                return
        stage = h.stage(run)
        sh(h.ssh, f"mkdir -p {stage}", check=True)
        subprocess.run(["rsync", "-a", "--delete", "--exclude", "q", "--exclude", "out", "--exclude", "worker.log",
                        f"{local_stage}/", f"{h.ssh}:{stage}/"], check=True, capture_output=True, timeout=900)
    sh(h.ssh, f"cd {h.stage(run)} && rm -rf q out && mkdir -p q/inbox q/running q/done out", check=True)
    h.ok = True


def start_worker(h, run, timeout, logdir):
    h.job = f"fleet-{run}-{h.name}".replace("_", "-")
    stage = h.stage(run)
    threads = str(max(1, h.nproc // h.slots))
    cmd = (f"cd {stage} && {h.py} worker.py {stage} {h.slots} {h.py} {threads} {timeout} "
           f"> {stage}/worker.log 2>&1")
    argv = [str(WATCHJOB), h.job] + (["--host", h.ssh] if h.ssh else []) + \
        ["--label", f"engine fleet {h.name}", "--", cmd]
    h.proc = subprocess.Popen(argv, stdout=open(logdir / f".watchjob-{h.name}.log", "w"),
                              stderr=subprocess.STDOUT)


def job_status(h):
    return subprocess.run([str(JOB), "status", h.job] + (["--host", h.ssh] if h.ssh else []),
                          capture_output=True, text=True).returncode   # 0 active, 1 failed, 2 finished, 3 unknown


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--commit", default="HEAD")
    ap.add_argument("--parts", default="")
    ap.add_argument("--hosts", default=",".join(HOSTS))
    ap.add_argument("--slots", default="", help="host=N,...")
    ap.add_argument("--timeout", default="1500")
    ap.add_argument("--setup-only", action="store_true")
    a = ap.parse_args()

    commit = subprocess.run(["git", "-C", str(REPO), "rev-parse", a.commit], capture_output=True, text=True,
                            check=True).stdout.strip()
    evid = {}
    for n in range(1, 40):
        st = next((d / f"{n}.step" for d in EVID if (d / f"{n}.step").exists()), None)
        if st and (MECH / f"{n}.stl").exists():
            evid[n] = st
    parts = [int(x) for x in a.parts.split(",") if x] or sorted(evid)
    missing = [n for n in parts if n not in evid]
    if missing:
        print(f"no evidence, skipped: {missing}")
    parts = sorted((n for n in parts if n in evid), key=lambda n: -(MECH / f"{n}.stl").stat().st_size)
    outdir = REPO / "runs/engine" / a.run
    outdir.mkdir(parents=True, exist_ok=True)

    # 1. freeze once
    local_stage = Path.home() / FLEET / a.run
    subprocess.run(["rm", "-rf", str(local_stage / "tools"), str(local_stage / "in")], check=True)
    (local_stage / "in").mkdir(parents=True)
    subprocess.run(f"git -C {REPO} archive {commit} tools | tar -x -C {local_stage}", shell=True, check=True)
    for n in parts:
        subprocess.run(["cp", str(MECH / f"{n}.stl"), str(local_stage / f"in/{n}.stl")], check=True)
        subprocess.run(["cp", str(evid[n]), str(local_stage / f"in/{n}.step")], check=True)
    (local_stage / "worker.py").write_text(WORKER)
    (local_stage / "COMMIT").write_text(commit + "\n")
    print(f"snapshot {commit[:10]} -> {local_stage}; {len(parts)} parts: {parts}", flush=True)

    # 2. hosts, in parallel
    slots_override = {k: int(v) for k, v in (x.split("=") for x in a.slots.split(",") if x)}
    hosts = [Host(n, HOSTS[n]) for n in a.hosts.split(",")]
    pinned = pins()
    ts = [threading.Thread(target=setup_host, args=(h, a.run, local_stage, pinned, slots_override)) for h in hosts]
    [t.start() for t in ts]; [t.join() for t in ts]
    for h in hosts:
        print(f"{h.name:10} {'OK  ' if h.ok else 'SKIP'} nproc={h.nproc} slots={h.slots} env={h.env_built} "
              f"{h.note}", flush=True)
    hosts = everyone = [h for h in hosts if h.ok]
    hosts = list(hosts)
    if not hosts or a.setup_only:
        return
    for h in hosts:
        start_worker(h, a.run, a.timeout, outdir)

    # 3-4. central work-stealing queue: push to free slots, pull what finished
    queue, t0, results = list(parts), time.time(), {}
    while True:
        for h in list(hosts):
            st = h.stage(a.run)
            r = sh(h.ssh, f"ls {st}/q/done", timeout=30)
            if r.returncode == 0:
                for n in map(int, r.stdout.split()):
                    if n in h.out:
                        sh(h.ssh, f"rm -f {st}/q/done/{n}", timeout=30)
                        src = [f"{st}/out/{n}.{e}" for e in ("json", "log", "time")]
                        if h.ssh:
                            subprocess.run(["rsync", "-a", "--ignore-missing-args"] +
                                           [f"{h.ssh}:{s}" for s in src] + [f"{outdir}/"], capture_output=True)
                        else:
                            subprocess.run(["cp"] + [s for s in src if Path(s).exists()] + [f"{outdir}/"])
                        tm = json.loads((outdir / f"{n}.time").read_text()) if (outdir / f"{n}.time").exists() \
                            else {"rc": -1, "seconds": None}
                        h.out.discard(n)
                        h.done.append((n, tm["seconds"], tm["rc"]))
                        results[n] = h.name
                        print(f"[{time.time() - t0:7.0f}s] {n:>2} done on {h.name}: {tm['seconds']} s rc={tm['rc']}",
                              flush=True)
            js = job_status(h)                          # 0 active, 1 failed, 2 finished, 3 unknown (not started yet?)
            if js in (1, 2) or (js == 3 and time.time() - t0 > 180):   # worker gone before STOP: requeue, drop host
                print(f"{h.name}: worker not active (job status), requeueing {sorted(h.out)}", flush=True)
                queue = sorted(queue + sorted(h.out), key=lambda n: -(MECH / f"{n}.stl").stat().st_size)
                h.out.clear()
                hosts.remove(h)
        while queue:                                    # next-largest part -> the host with the most free slot share
            free = [h for h in hosts if len(h.out) < h.slots]
            if not free:
                break
            h = max(free, key=lambda h: ((h.slots - len(h.out)) / h.slots, h.nproc))
            n = queue.pop(0)
            h.out.add(n)
            sh(h.ssh, f"touch {h.stage(a.run)}/q/inbox/{n}", timeout=30, check=True)
            print(f"[{time.time() - t0:7.0f}s] {n:>2} -> {h.name}", flush=True)
        if not hosts:
            print(f"ALL HOSTS LOST; unfinished: {queue}")
            break
        if not queue and not any(h.out for h in hosts):
            break
        time.sleep(10)
    for h in hosts:
        sh(h.ssh, f"touch {h.stage(a.run)}/q/STOP", timeout=30)
    for h in hosts:
        h.proc.wait()

    # 5. summary + compare
    print(f"\nfleet {a.run} @ {commit[:10]}: {len(results)}/{len(parts)} parts in {time.time() - t0:.0f} s")
    for h in everyone:
        secs = [s for _, s, _ in h.done if s is not None]
        print(f"{h.name:10} nproc={h.nproc} slots={h.slots} parts={len(h.done)} "
              f"mean={sum(secs) / len(secs) if secs else 0:.0f}s  " +
              " ".join(f"{n}:{s}s{'' if rc == 0 else f'(rc={rc})'}" for n, s, rc in h.done))
    subprocess.run([sys.executable, str(REPO / "tools/engine/compare.py"), str(outdir)])


if __name__ == "__main__":
    main()
