"""Profile a command: run it in its own cgroup and sample, every PERIOD s, the cgroup's CPU and memory and every
process in it (name, short cmdline, CPU ticks). One JSON line per sample in <out>.jsonl; stage markers written by
the profiled tools (lines "MARK <name> <start|end> <unix time>" on stdout/stderr) go to <out>.marks.

usage: cgprof.py <out_prefix> -- <cmd...>
"""
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

PERIOD = 0.5
HZ = os.sysconf("SC_CLK_TCK")


def cgroup_of(unit):
    for _ in range(100):
        r = subprocess.run(["systemctl", "--user", "show", "-p", "ControlGroup", "--value", unit],
                           capture_output=True, text=True).stdout.strip()
        if r and Path("/sys/fs/cgroup" + r).exists():
            return Path("/sys/fs/cgroup" + r)
        time.sleep(0.05)
    return None


EXTRA = re.compile(r"freecad|FreeCAD|Xvfb")               # the FreeCAD snap runs in its own cgroup (snap.freecad.*)
BOOT = time.time() - float(Path("/proc/uptime").read_text().split()[0])
T_START = time.time()


def extra_pids():
    """FreeCAD / Xvfb processes started after the profiler, wherever their cgroup is."""
    out = []
    for d in Path("/proc").iterdir():
        if not d.name.isdigit():
            continue
        try:
            st = (d / "stat").read_text()
            start = BOOT + int(st[st.rindex(")") + 2:].split()[19]) / HZ
            if start >= T_START - 1 and EXTRA.search((d / "cmdline").read_bytes().decode(errors="replace")):
                out.append(d.name)
        except (OSError, ValueError, IndexError):
            continue
    return out


def procs(cg):
    out = []
    try:
        pids = (cg / "cgroup.procs").read_text().split()
    except OSError:
        pids = []
    pids = list(dict.fromkeys(pids + extra_pids()))
    for p in pids:
        try:
            st = Path(f"/proc/{p}/stat").read_text()
            f = st[st.rindex(")") + 2:].split()
            cmd = Path(f"/proc/{p}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
            out.append([int(p), cmd[:160], (int(f[11]) + int(f[12])) / HZ, int(f[21]) * os.sysconf("SC_PAGE_SIZE") >> 20])
        except (OSError, ValueError, IndexError):
            continue
    return out


def main():
    i = sys.argv.index("--")
    pre, cmd = Path(sys.argv[1]), sys.argv[i + 1:]
    unit = f"cgprof-{os.getpid()}-{int(time.time())}"
    proc = subprocess.Popen(["systemd-run", "--user", "--scope", "--quiet", "--collect", f"--unit={unit}",
                             "-p", "MemorySwapMax=0", *cmd], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    cg = cgroup_of(unit + ".scope")
    done = threading.Event()
    samples = open(str(pre) + ".jsonl", "w")

    def sample():
        while not done.is_set():
            t = time.time()
            try:
                cpu = int(next(ln for ln in (cg / "cpu.stat").read_text().splitlines() if ln.startswith("usage_usec")).split()[1])
                mem = int((cg / "memory.current").read_text()) >> 20
            except (OSError, StopIteration, TypeError):
                cpu = mem = None
            samples.write(json.dumps({"t": round(t, 2), "cpu_us": cpu, "mem_mb": mem, "procs": procs(cg) if cg else []}) + "\n")
            done.wait(PERIOD)

    th = threading.Thread(target=sample, daemon=True); th.start()
    marks, log = open(str(pre) + ".marks", "w"), open(str(pre) + ".out", "w")
    for line in proc.stdout:
        log.write(line); log.flush()
        if line.startswith("MARK "):
            marks.write(line); marks.flush()
    rc = proc.wait()
    done.set(); th.join(); samples.close()
    print(json.dumps({"rc": rc, "samples": str(pre) + ".jsonl"}))
    sys.exit(rc)


if __name__ == "__main__":
    main()
