#!/usr/bin/env python3
"""Is each cylindrical patch of the MESH represented by an analytic curved face on the model?

The radius-matching metric lies on real parts, and a previous session proved it: mesh2step's own
quads.classify returns 30 and 80 "cylinders" on parts 12 and 23 that collapse to 8 and 19 distinct
1% clusters, so the same physical feature is counted many times at radii differing in the fourth
decimal and then scored as uncovered for numerical noise. Radius equality also cannot tell a right
radius in the wrong place from a real recovery.

This asks the question that survives both objections, and needs no CAD truth, so it works on
~/corpora/mechparts where the parts that matter live: take each mesh cylinder patch, and measure
the p95 distance of ITS OWN triangles to the nearest face of the built model. Represented means
close AND landing on an analytic curved face (cylinder, cone, torus, sphere) rather than a plane --
a patch sitting on a plane is a faceted wall, which is exactly the failure the user sees.

usage: patch_representation.py --url http://127.0.0.1:PORT --stl A.stl [B.stl ...] [--jobs 4]
       patch_representation.py --url ... --dir ~/corpora/mechparts [--out rep.tsv]
"""
from __future__ import annotations
import argparse, concurrent.futures as cf, json, sys, tempfile, time, urllib.request
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from mesh2step.feature import RECON, _mesh  # noqa: E402

TOL_REL = 0.01          # a patch is "on" the model within 1% of the part diagonal


def mesh_patches(tri: np.ndarray):
    """Cylindrical patches the tessellation shows, as (radius, triangle indices)."""
    sys.path.insert(0, str(RECON))
    from quads import classify
    out = []
    for o in classify(tri)[2]:
        if o[0] != "cylinder":
            continue
        # quads.classify yields (kind, n_quads, radius, axis, triangle_indices) -- the members
        # are o[4]; o[3] is the axis, and taking it by mistake silently measures the whole mesh.
        out.append((o[2], o[4]))
    return out


def model_faces(step: Path):
    """Every face as (kind, BRepAdaptor face handle) for a nearest-face query."""
    from OCP.BRep import BRep_Builder
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import (GeomAbs_Cone, GeomAbs_Cylinder, GeomAbs_Plane, GeomAbs_Sphere,
                             GeomAbs_Torus)
    from OCP.STEPControl import STEPControl_Reader
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp
    from OCP.TopoDS import TopoDS, TopoDS_Compound
    from OCP.TopTools import TopTools_IndexedMapOfShape
    r = STEPControl_Reader()
    if r.ReadFile(str(step)) != 1:
        return None, {}
    r.TransferRoots()
    sh = r.OneShape()
    if sh.IsNull():
        return None, {}
    fm = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(sh, TopAbs_FACE, fm)
    names = {GeomAbs_Plane: "plane", GeomAbs_Cylinder: "cylinder", GeomAbs_Cone: "cone",
             GeomAbs_Sphere: "sphere", GeomAbs_Torus: "torus"}
    groups: dict[str, TopoDS_Compound] = {}
    builders = {}
    for i in range(1, fm.Extent() + 1):
        f = TopoDS.Face_s(fm.FindKey(i))
        kind = names.get(BRepAdaptor_Surface(f).GetType(), "other")
        if kind not in groups:
            c = TopoDS_Compound(); b = BRep_Builder(); b.MakeCompound(c)
            groups[kind], builders[kind] = c, b
        builders[kind].Add(groups[kind], f)
    return sh, groups


def _dist(pt, comp) -> float:
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    from OCP.gp import gp_Pnt
    d = BRepExtrema_DistShapeShape(BRepBuilderAPI_MakeVertex(gp_Pnt(*map(float, pt))).Vertex(), comp)
    d.Perform()
    return d.Value() if d.IsDone() else float("inf")


def represent(stl: Path, step: Path, samples: int = 12) -> dict:
    tri = _mesh(stl)
    lo, hi = tri.reshape(-1, 3).min(0), tri.reshape(-1, 3).max(0)
    diag = float(np.linalg.norm(hi - lo))
    tol = TOL_REL * diag
    _, groups = model_faces(step)
    if not groups:
        return {"patches": 0, "curved": 0, "plane": 0, "far": 0, "diag": diag}
    curved = {k: v for k, v in groups.items() if k != "plane"}
    n_curved = n_plane = n_far = 0
    patches = mesh_patches(tri)
    for _radius, idx in patches:
        # CENTROIDS, not vertices: a hole wall's rim vertices lie on the flat face as exactly as
        # on the cylinder, so sampling them scores a perfectly rebuilt hole as "plane". Measured on
        # L06_flange_plate, which recovers all 7 of its cylinders and read 2 of 8 patches curved.
        pts = tri[list(idx)].mean(axis=1) if idx is not None else tri.mean(axis=1)
        pick = pts[np.linspace(0, len(pts) - 1, min(samples, len(pts))).astype(int)]
        dc = min((np.percentile([_dist(p, c) for p in pick], 95) for c in curved.values()),
                 default=float("inf"))
        dp = (np.percentile([_dist(p, groups["plane"]) for p in pick], 95)
              if "plane" in groups else float("inf"))
        if dc <= tol and dc <= dp:
            n_curved += 1
        elif dp <= tol:
            n_plane += 1
        else:
            n_far += 1
    return {"patches": len(patches), "curved": n_curved, "plane": n_plane, "far": n_far,
            "diag": diag}


def convert(url: str, stl: Path, timeout: float) -> tuple[dict, bytes | None]:
    boundary = "----m2srep"
    body = b""
    for k, v in {"engine": "trueform", "feature": "true", "schema": "ap214"}.items():
        body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n").encode()
    body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
             f"filename=\"{stl.name}\"\r\nContent-Type: application/octet-stream\r\n\r\n").encode()
    body += stl.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(url + "/api/convert", data=body,
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=300) as r:
        res = json.loads(r.read())
    t0 = time.time()
    while res.get("pending"):
        if time.time() - t0 > timeout:
            return {"status": "TIMEOUT"}, None
        time.sleep(2.0)
        with urllib.request.urlopen(f"{url}/api/job/{res['job']}", timeout=60) as r:
            res = json.loads(r.read())
    if not res.get("download_token"):
        return {"status": "NO_DOWNLOAD"}, None
    with urllib.request.urlopen(f"{url}/api/download/{res['download_token']}", timeout=300) as r:
        return res, r.read()


def one(url: str, stl: Path, timeout: float) -> dict:
    row = {"model": stl.stem, "patches": 0, "curved": 0, "plane": 0, "far": 0,
           "backend": "", "status": "OK", "s": 0.0}
    t0 = time.time()
    try:
        res, data = convert(url, stl, timeout)
    except Exception as e:  # noqa: BLE001
        row["status"] = f"HTTP:{type(e).__name__}"
        return row
    row["s"] = round(time.time() - t0, 1)
    if data is None:
        row["status"] = res.get("status", "NO_OUTPUT")
        return row
    row["backend"] = (res.get("stats") or {}).get("backend", "")
    with tempfile.NamedTemporaryFile(suffix=".step", delete=False) as fh:
        fh.write(data)
        step = Path(fh.name)
    try:
        row.update({k: v for k, v in represent(stl, step).items() if k != "diag"})
    except Exception as e:  # noqa: BLE001
        row["status"] = f"REPERR:{type(e).__name__}"
    finally:
        step.unlink(missing_ok=True)
    return row


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--stl", nargs="*", default=[])
    ap.add_argument("--dir", default=None)
    ap.add_argument("--out", default="representation.tsv")
    ap.add_argument("--jobs", type=int, default=3)
    ap.add_argument("--timeout", type=float, default=900.0)
    a = ap.parse_args()

    stls = [Path(p) for p in a.stl]
    if a.dir:
        stls += sorted(Path(a.dir).expanduser().glob("*.stl"))
    print(f"{len(stls)} parts, jobs={a.jobs}", flush=True)

    rows = []
    with cf.ThreadPoolExecutor(max_workers=a.jobs) as ex:
        for r in cf.as_completed([ex.submit(one, a.url, p, a.timeout) for p in stls]):
            row = r.result()
            rows.append(row)
            print(f"  {row['model']:20} patches={row['patches']:4} curved={row['curved']:4} "
                  f"plane={row['plane']:4} far={row['far']:4} {row['backend']:8} "
                  f"{row['status']} {row['s']}s", flush=True)

    rows.sort(key=lambda r: r["model"])
    cols = ["model", "patches", "curved", "plane", "far", "backend", "status", "s"]
    Path(a.out).write_text("\t".join(cols) + "\n"
                           + "\n".join("\t".join(str(r[c]) for c in cols) for r in rows) + "\n")
    ok = [r for r in rows if r["status"] == "OK" and r["patches"]]
    tp = sum(r["patches"] for r in ok)
    tc = sum(r["curved"] for r in ok)
    print(f"\nREPRESENTATION {len(ok)}/{len(rows)} parts with patches")
    print(f"  mesh cylinder patches on an ANALYTIC CURVED face: {tc}/{tp} = "
          f"{100.0*tc/tp if tp else 0:.1f}%")
    print(f"  on a PLANE (still faceted): {sum(r['plane'] for r in ok)}   "
          f"not represented at all: {sum(r['far'] for r in ok)}")
    print(f"  parts with every patch curved: {sum(1 for r in ok if r['curved'] == r['patches'])}"
          f"  parts with none: {sum(1 for r in ok if r['curved'] == 0)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
