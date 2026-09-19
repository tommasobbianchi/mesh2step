#!/usr/bin/env python3
"""How many of a part's cylinders actually reach the CAD? (bd projects-3md)

The shipped gates all measure the BUILD: `feature.support` asks what share of the cylinders we
built are backed by the mesh, `radius_audit` asks how many built faces have a truth radius. Both
have the built set as their denominator, so a conversion that recovers one hole out of twelve and
gets it right scores perfectly. COVERAGE turns the fraction the other way up -- of the cylinders
the part HAS, how many came back -- which is the only form of the number a user recognises.

Denominator, in order of honesty:
  * truth  -- cylindrical FACES of the source B-Rep, expanded from truth.json's `cyl_radii_hist`
    (corpus only). Never `cyl_radii`: that list is deduplicated, so SpeedTestStructure reads as
    4 cylinders instead of 285 and a build recovering 7 of them would score near-perfect.
  * mesh   -- cylinders the tessellation shows (quads.classify). The only denominator available on
    a user upload, and measured here against truth so its error is known rather than assumed.

Pairing is greedy and ONE-TO-ONE on radius, largest first: four M3 holes are four cylinders, and a
build that recovers one of them must not score four. A matched radius is still only an upper bound
on recall -- the right radius in the wrong place counts as recovered (radius_audit.py says the
same). The number is therefore optimistic by construction; it is compared against itself over time.

Runs the conversion through the WEBAPP, not the engine, so what is measured is the STEP a user
receives: engine fallback, feature upgrade, edgebuild and canonize included.

usage: cylinder_coverage.py --url http://127.0.0.1:PORT [--variant normal] [--jobs 4]
                            [--out coverage.tsv] [--limit N] [--timeout 600]
"""
from __future__ import annotations
import argparse, concurrent.futures as cf, json, sys, time, urllib.error, urllib.request
from pathlib import Path

CORPUS = Path.home() / "corpora/cadbench"
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from mesh2step.feature import pair_radii  # noqa: E402  the one definition of "the same radius"


def step_cylinder_radii(data: bytes) -> list[float]:
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Cylinder
    from OCP.STEPControl import STEPControl_Reader
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp
    from OCP.TopoDS import TopoDS
    from OCP.TopTools import TopTools_IndexedMapOfShape
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".step") as fh:
        fh.write(data)
        fh.flush()
        r = STEPControl_Reader()
        if r.ReadFile(fh.name) != 1:
            return []
        r.TransferRoots()
        fm = TopTools_IndexedMapOfShape()
        TopExp.MapShapes_s(r.OneShape(), TopAbs_FACE, fm)
    out = []
    for i in range(1, fm.Extent() + 1):
        s = BRepAdaptor_Surface(TopoDS.Face_s(fm.FindKey(i)))
        if s.GetType() == GeomAbs_Cylinder:
            out.append(s.Cylinder().Radius())
    return out


def _post(url: str, stl: Path, fields: dict) -> dict:
    boundary = "----m2scov"
    body = b""
    for k, v in fields.items():
        body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n").encode()
    body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{stl.name}\""
             "\r\nContent-Type: application/octet-stream\r\n\r\n").encode()
    body += stl.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(url + "/api/convert", data=body,
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read())


def convert(url: str, stl: Path, timeout: float) -> dict:
    """POST, follow the job to the end, return the finished result payload."""
    res = _post(url, stl, {"engine": "trueform", "feature": "true", "schema": "ap214"})
    t0 = time.time()
    while res.get("pending"):
        if time.time() - t0 > timeout:
            return {"status": "TIMEOUT"}
        time.sleep(2.0)
        with urllib.request.urlopen(f"{url}/api/job/{res['job']}", timeout=60) as r:
            res = json.loads(r.read())
    return res


def mesh_cylinders(stl: Path) -> int:
    from mesh2step.feature import _mesh, mesh_cylinder_radii
    return len(mesh_cylinder_radii(_mesh(stl)))


def truth_radii(meta: dict) -> list[float]:
    """One entry per cylindrical FACE. The deduplicated `cyl_radii` is not a count of anything."""
    return [float(r) for r, n in meta["cyl_radii_hist"].items() for _ in range(n)]


def one(url: str, name: str, meta: dict, variant: str, timeout: float) -> dict:
    stl = Path(meta["stl"].get(variant, meta["stl"]["fine"])["path"])
    want = truth_radii(meta)
    row = {"model": name, "tris": meta["stl"].get(variant, meta["stl"]["fine"])["triangles"],
           "truth": len(want), "truth_radii": len(meta["cyl_radii_hist"]),
           "mesh": -1, "built": 0, "recovered": 0, "status": "OK", "s": 0.0}
    t0 = time.time()
    try:
        row["mesh"] = mesh_cylinders(stl)
    except Exception as e:  # noqa: BLE001  a detector crash is data, not a stop
        row["status"] = f"MESHERR:{type(e).__name__}"
    try:
        res = convert(url, stl, timeout)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
        row["status"], row["s"] = f"HTTP:{e}"[:40], time.time() - t0
        return row
    row["s"] = round(time.time() - t0, 1)
    if not res.get("download_token"):
        row["status"] = res.get("status") or f"NO_DOWNLOAD:{str(res)[:60]}"
        return row
    with urllib.request.urlopen(f"{url}/api/download/{res['download_token']}", timeout=120) as r:
        built = step_cylinder_radii(r.read())
    row["built"] = len(built)
    row["recovered"] = pair_radii(built, want)
    row["backend"] = (res.get("stats") or {}).get("backend", "")
    return row


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--variant", default="normal")
    ap.add_argument("--corpus", default=str(CORPUS))
    ap.add_argument("--out", default="coverage.tsv")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--timeout", type=float, default=600.0)
    a = ap.parse_args()

    truth = json.loads((Path(a.corpus) / "truth.json").read_text())
    # Only parts that HAVE cylinders: coverage is undefined with an empty denominator, and the
    # no-cylinder models are already the negative control radius_audit covers.
    models = {k: v for k, v in truth.items()
              if v["cyl_faces"] > 0 and not k.startswith("NEG_") and "cyl_radii_hist" in v
              and (a.variant in v["stl"] or "fine" in v["stl"])}
    names = sorted(models)[: a.limit or None]
    print(f"{len(names)} cylinder-bearing models, variant={a.variant}, jobs={a.jobs}", flush=True)

    rows = []
    with cf.ThreadPoolExecutor(max_workers=a.jobs) as ex:
        futs = {ex.submit(one, a.url, n, models[n], a.variant, a.timeout): n for n in names}
        for f in cf.as_completed(futs):
            r = f.result()
            rows.append(r)
            print(f"  {r['model']:34} truth={r['truth']:3} mesh={r['mesh']:3} built={r['built']:3} "
                  f"recovered={r['recovered']:3} {r['status']} {r['s']}s", flush=True)

    rows.sort(key=lambda r: r["model"])
    cols = ["model", "tris", "truth", "truth_radii", "mesh", "built", "recovered", "status", "s",
            "backend"]
    Path(a.out).write_text("\t".join(cols) + "\n"
                           + "\n".join("\t".join(str(r.get(c, "")) for c in cols) for r in rows) + "\n")

    ok = [r for r in rows if r["status"] == "OK"]
    tt, rr = sum(r["truth"] for r in ok), sum(r["recovered"] for r in ok)
    # macro: every part counts once, so one 285-cylinder model cannot carry the whole corpus
    macro = sum(r["recovered"] / r["truth"] for r in ok if r["truth"]) / max(1, len(ok))
    full = sum(1 for r in ok if r["recovered"] >= r["truth"])
    most = sum(1 for r in ok if r["recovered"] >= 0.5 * r["truth"])
    none = sum(1 for r in ok if r["recovered"] == 0)
    print(f"\nBASELINE {len(ok)}/{len(rows)} converted")
    print(f"  cylinders recovered   {rr}/{tt} = {100.0*rr/tt if tt else 0:.1f}%  (micro)")
    print(f"  cylinders recovered   {100.0*macro:.1f}%  (macro, mean over models)")
    print(f"  models fully recovered {full}  >=half {most}  zero {none}")
    md = sum(r["mesh"] for r in ok if r["mesh"] >= 0)
    print(f"  mesh detector as denominator: {md} vs truth {tt} "
          f"({100.0*md/tt if tt else 0:.0f}% of the real count)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
