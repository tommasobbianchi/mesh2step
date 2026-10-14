"""Does the V-gauge help (bd projects-vgj7.4)? cellbuild on each scanbench part from what a simulated user gets
(scanuser_eval.user on the prepped scan with scanransac suggestions, the rest filled from detect, as the server builds),
BEFORE and AFTER the user also places a gauge on every truth 90-degree edge between two CAD planes; AFTER_CHECKED
keeps only the gauges whose L lies on the right pair of faces (what a user looking at the preview accepts).

The click is the scan triangle nearest the middle of the edge (the CAD face adjacency edge nearest the centroid of
that face pair's shared edges); a rejected gauge (400) is retried wider twice (the page's "Retry wider", x1.5 each),
then not placed and counted. Builds count when
valid with one solid (scanuser_eval's criterion). No tuning: the gauge's constants are the shipped ones.

usage: python3 tools/gauge_eval.py [--limit N] [--jobs 3] --out results.json   (under watchjob)
"""

import argparse
import ast
import json
import subprocess
import sys
import tempfile
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tools"), str(ROOT / "tools/feature_recon"), str(ROOT / "tests")]
import scanbench as B  # noqa: E402
import scanuser_eval as U  # noqa: E402

from mesh2step import guide  # noqa: E402

CELLBUILD = ROOT / "tools/feature_recon/cellbuild.py"
WRONG_DEG = 10.0   # a gauge plane this far from both truth normals is on another face: visibly wrong


def truth_edges(clean, owner, truth):
    """-> [(face a, face b, point on the middle of their shared edge, true normals)] for CAD plane pairs at 90 deg."""
    kinds = {f: k for f, (k, _) in truth.items()}
    adj, ae = clean.face_adjacency, clean.face_adjacency_edges
    fa, fb = owner[adj[:, 0]], owner[adj[:, 1]]
    n = {}
    out = []
    for a, b in {tuple(sorted(p)) for p in zip(fa.tolist(), fb.tolist(), strict=True) if p[0] != p[1]}:
        if kinds.get(a) != "plane" or kinds.get(b) != "plane":
            continue
        for f in (a, b):
            if f not in n:
                t = owner == f
                v = (clean.face_normals[t] * clean.area_faces[t, None]).sum(0)
                n[f] = v / np.linalg.norm(v)
        if abs(n[a] @ n[b]) > np.sin(np.radians(1)):
            continue
        m = ((fa == a) & (fb == b)) | ((fa == b) & (fb == a))
        mid = clean.vertices[ae[m]].mean(1)
        out.append((a, b, mid[np.argmin(np.linalg.norm(mid - mid.mean(0), axis=1))], (n[a], n[b])))
    return out


def cellbuild(stl, labels, td, tag):
    out = Path(td) / f"{tag}.step"
    lp = Path(td) / f"{tag}.json"
    lp.write_text(json.dumps(labels))
    try:
        p = subprocess.run([sys.executable, str(CELLBUILD), str(stl), str(out), "--labels", str(lp)],
                           capture_output=True, text=True, timeout=900)
        line = next((ln for ln in p.stdout.splitlines() if ln.startswith(("RESULT ", "FAIL"))), p.stdout[-200:] or
                    f"exit {p.returncode}")
    except subprocess.TimeoutExpired:
        return {"ok": False, "result": "timeout"}
    res = ast.literal_eval(line[7:]) if line.startswith("RESULT ") else None
    return {"ok": bool(res and res["valid"] and res["solids"] == 1), "result": res or line[:200]}


def selections(n, picks, det, gauges):
    """As the server builds: gauges and the user's picks, the unselected rest from detect. A gauge drops triangles a
    curved pick already has (the page does the same on Accept)."""
    sel, used = [], set()
    curved = {t for p in picks for t in p["triangles"]}
    for g in gauges:
        planes = [dict(p, triangles=[t for t in p["triangles"] if t not in curved and t not in used]) for p in g["planes"]]
        tris = [t for p in planes for t in p["triangles"]]
        used.update(tris)
        sel.append(dict(g, planes=planes, triangles=tris))
    for p in picks:
        t = [x for x in p["triangles"] if x not in used]
        used.update(t)
        if t:
            sel.append(dict(p, triangles=t))
    lab = np.asarray(det["label"])
    for i, k in det["kinds"].items():
        t = [x for x in np.flatnonzero(lab == i).tolist() if x not in used]
        if len(t) >= 3:
            used.update(t)
            sel.append({"kind": k, "surface": k, "triangles": t, "params": det["params"][i], "fill": True})
    return guide.labels(n, sel)


def run_part(part):
    import gauge as G
    from gauge import gauge
    from scanprep import _noise, prep
    from scanransac import detect

    clean, owner, truth = B.load(part)
    noisy = B.scanify(clean)
    pm = prep(noisy)[0]
    labels = B.transfer(clean, owner, pm)
    det = detect(pm)
    _, picks = U.user(pm, labels, truth, det, noisy)
    noise = _noise(noisy.vertices, noisy.faces)
    diag = float(np.linalg.norm(noisy.extents))
    edges = truth_edges(clean, owner, truth)
    C = pm.triangles_center
    gauges, rejected, err, tries = [], [], [], []
    for _a, _b, q, tn in edges:
        t = int(np.argmin(np.linalg.norm(C - q, axis=1)))
        g = None
        for k in range(3):   # the page's "Retry wider": the window x1.5 per retry
            try:
                g = gauge(pm, t, raw=noisy, noise=noise, radius=G.RADIUS * diag * 1.5 ** k)
                break
            except ValueError as e:
                msg = str(e)[:80]
        if g is None:
            rejected.append(msg)
            continue
        tries.append(k + 1)
        g["kind"] = "gauge"
        g["triangles"] = [x for p in g["planes"] for x in p["triangles"]]
        gauges.append(g)
        # normal error of the gauge against the truth pair, degrees
        err.append(max(min(np.degrees(np.arccos(min(1.0, abs(np.dot(p["normal"], v))))) for v in tn)
                       for p in g["planes"]))
    row = {"part": part, "tris": len(pm.faces), "edges90": len(edges), "gauges": len(gauges),
           "rejected": rejected, "tries": tries, "normal_err_deg": [round(float(x), 2) for x in err], "diag": diag,
           "noise": noise}
    with tempfile.TemporaryDirectory() as td:
        stl = Path(td) / "prep.stl"
        pm.export(stl)
        row["before"] = cellbuild(stl, selections(len(pm.faces), picks, det, []), td, "before")
        row["after"] = (cellbuild(stl, selections(len(pm.faces), picks, det, gauges), td, "after")
                        if gauges else row["before"])
        # a user who looks at the preview cancels an L lying on the wrong pair of faces (> WRONG_DEG off the truth)
        ok = [g for g, e in zip(gauges, err, strict=True) if e <= WRONG_DEG]
        row["after_checked"] = (row["after"] if len(ok) == len(gauges) else
                                cellbuild(stl, selections(len(pm.faces), picks, det, ok), td, "checked")
                                if ok else row["before"])
    print(json.dumps({k: row[k] for k in ("part", "edges90", "gauges")} | {
        "before": row["before"]["ok"], "after": row["after"]["ok"], "checked": row["after_checked"]["ok"]}),
          flush=True)
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    parts = json.loads((ROOT / "tools/scanbench_parts.json").read_text())[: a.limit]
    with ProcessPoolExecutor(a.jobs) as ex:
        rows = list(ex.map(run_part, parts))
    Path(a.out).write_text(json.dumps(rows, indent=1, default=float))
    s = {"parts": len(rows), "before_ok": sum(r["before"]["ok"] for r in rows),
         "after_ok": sum(r["after"]["ok"] for r in rows),
         "after_checked_ok": sum(r["after_checked"]["ok"] for r in rows),
         "checked_fixed": [r["part"] for r in rows if r["after_checked"]["ok"] and not r["before"]["ok"]],
         "checked_broken": [r["part"] for r in rows if r["before"]["ok"] and not r["after_checked"]["ok"]],
         "wrong_pair_gauges": sum(e > WRONG_DEG for r in rows for e in r["normal_err_deg"]),
         "fixed": [r["part"] for r in rows if r["after"]["ok"] and not r["before"]["ok"]],
         "broken": [r["part"] for r in rows if r["before"]["ok"] and not r["after"]["ok"]],
         "parts_with_gauges": sum(r["gauges"] > 0 for r in rows), "gauges": sum(r["gauges"] for r in rows),
         "edges90": sum(r["edges90"] for r in rows), "rejected": sum(len(r["rejected"]) for r in rows)}
    print("SUMMARY", json.dumps(s))


if __name__ == "__main__":
    main()
