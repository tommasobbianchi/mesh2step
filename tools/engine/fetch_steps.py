"""Evidence for the engine: each corpus part converted by the live service (trueform + feature pass), the STEP
kept. Loopback caller: the paid AI rebuild is never triggered (_recon_allowed refuses 127.0.0.1).

usage: fetch_steps.py <out_dir> <stl>...
"""
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8000"
FEATURE = "false" if "--no-feature" in sys.argv else "true"   # the feature pass times out on some parts (6)


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=60) as r:
        return r.read()


def convert(stl, out):
    r = subprocess.run(["curl", "-s", "-m", "900", "-F", f"file=@{stl}", "-F", "engine=trueform",
                        "-F", f"feature={FEATURE}", BASE + "/api/convert"], capture_output=True, text=True)
    d = json.loads(r.stdout)
    t0 = time.time()
    while d.get("pending") and time.time() - t0 < 3600:
        time.sleep(10)
        d = json.loads(get(f"/api/job/{d['job']}"))
    if not d.get("download_token"):
        return {"ok": False, "detail": str(d)[:300]}
    out.write_bytes(get(f"/api/download/{d['download_token']}"))
    return {"ok": True, "seconds": round(time.time() - t0, 1), "stats": {k: d.get("stats", {}).get(k)
            for k in ("backend", "faces", "surface_types") if k in d.get("stats", {})}}


if __name__ == "__main__":
    od = Path(sys.argv[1])
    for stl in [a for a in sys.argv[2:] if not a.startswith("--")]:
        out = od / (Path(stl).stem + ".step")
        if out.exists():
            continue
        try:
            res = convert(stl, out)
        except Exception as e:                           # noqa: BLE001
            res = {"ok": False, "detail": repr(e)[:300]}
        print(Path(stl).stem, json.dumps(res), flush=True)
