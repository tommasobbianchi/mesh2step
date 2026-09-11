#!/usr/bin/env python3
"""Augment truth.json with the PER-FACE cylinder radius histogram.

truth.json stored `cyl_radii` deduplicated, which hides the distribution: SpeedTestStructure
lists [0.2, 10, 20] and looks balanced, while 278 of its 285 cylinder faces are the 0.2.
Recall denominators built on the deduplicated list are wrong wherever one radius dominates.

Adds `cyl_radii_hist` : {radius: face count}. Non-destructive; rewrites truth.json in place.
"""
import json
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

TRUTH = Path.home() / "corpora/cadbench/truth.json"


def hist_of(name, src):
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Cylinder
    from OCP.STEPControl import STEPControl_Reader
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp
    from OCP.TopoDS import TopoDS
    from OCP.TopTools import TopTools_IndexedMapOfShape
    import collections
    r = STEPControl_Reader()
    if r.ReadFile(src) != 1:
        return name, {}
    r.TransferRoots()
    m = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(r.OneShape(), TopAbs_FACE, m)
    c = collections.Counter()
    for i in range(1, m.Extent() + 1):
        s = BRepAdaptor_Surface(TopoDS.Face_s(m.FindKey(i)))
        if s.GetType() == GeomAbs_Cylinder:
            c[round(s.Cylinder().Radius(), 6)] += 1
    return name, {str(k): v for k, v in sorted(c.items())}


def main():
    truth = json.loads(TRUTH.read_text())
    todo = [(k, v["src"]) for k, v in truth.items() if v.get("cyl_faces")]
    print(f"{len(todo)} models with cylinders")
    with ProcessPoolExecutor(max_workers=6) as pool:
        futs = [pool.submit(hist_of, k, s) for k, s in todo]
        for i, f in enumerate(as_completed(futs), 1):
            name, h = f.result()
            truth[name]["cyl_radii_hist"] = h
            if i % 40 == 0:
                print(f"  [{i}/{len(todo)}]", flush=True)
    TRUTH.write_text(json.dumps(truth, indent=1))
    print("truth.json updated with cyl_radii_hist")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
