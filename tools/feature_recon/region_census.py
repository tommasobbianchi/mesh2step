"""Region growing vs cadbench truth face counts, per model and in aggregate.
usage: python3 region_census.py <variant> [limit]   -> one JSON line per model, then a summary"""
import json, sys, time
from pathlib import Path
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from regions import regions
from slice import load

C = Path.home() / "corpora/cadbench"
T = json.loads((C / "truth.json").read_text())
variant = sys.argv[1]; limit = int(sys.argv[2]) if len(sys.argv) > 2 else 10**9
rows = []
for p in sorted(C.glob(f"*_{variant}.stl"))[:limit]:
    key = p.stem[: -len(variant) - 1]; t = T.get(key, {}); t0 = time.time()
    try:
        r = regions(load(str(p)))
    except Exception as e:  # noqa: BLE001 - a census row, not a gate
        print(json.dumps({"model": key, "error": repr(e)}), flush=True); continue
    c = r["counts"]
    row = {"model": key, "tris": r["tris"], "truth": [t.get("planar_faces"), t.get("cyl_faces"), t.get("other_faces")],
           "got": [c.get("plane", 0), c.get("cylinder", 0), c.get("cone", 0) + c.get("sphere", 0) + c.get("torus", 0)],
           "unassigned_pct": r["unassigned_pct"], "sec": round(time.time() - t0, 1)}
    rows.append(row); print(json.dumps(row), flush=True)
# *_recon truth is read from an earlier RECONSTRUCTION's STEP (L01_cube_recon: 32 B-spline faces;
# L03_hex_prism_recon: a cylinder), not from CAD: score only the CAD-sourced models.
ok = [r for r in rows if None not in r["truth"] and not r["model"].endswith("_recon")]
exact = [r for r in ok if r["got"] == r["truth"]]
for i, k in enumerate(("planes", "cylinders", "other")):
    eq = sum(1 for r in ok if r["got"][i] == r["truth"][i])
    print(f"{k}: exact {eq}/{len(ok)}  truth total {sum(r['truth'][i] for r in ok)}  got total {sum(r['got'][i] for r in ok)}")
print(f"all three exact: {len(exact)}/{len(ok)}; median unassigned "
      f"{sorted(r['unassigned_pct'] for r in ok)[len(ok) // 2] if ok else 'n/a'}%")
