#!/usr/bin/env python3
"""Rebuild the benchmark corpus from its SOURCE B-Reps, durably and reproducibly.

WHY THIS EXISTS
    The corpus lived in /tmp/awk/cadbench and was destroyed by the 2026-09-10 08:41
    reboot, together with truth.json. It had no generator -- it had been assembled by
    hand over weeks -- so a single reboot cost every gate its measuring stick. This
    script is the generator that should have existed: it reads only sources that live
    outside /tmp, and writes outside /tmp.

WHAT IS DIFFERENT, AND BETTER, THAN WHAT WAS LOST
    truth.json used to be hand-maintained per-model counts. Here every count is DERIVED
    from the source B-Rep by walking its faces and edges, so the truth is reproducible
    and cannot drift from the CAD it claims to describe.

WHAT CANNOT BE RECOVERED, STATED PLAINLY
    The exact membership of the old 57-model truth set and the old 54 NEG_* negatives is
    not recorded anywhere that survived. This script therefore defines both sets by an
    explicit, documented RULE (see SOURCES below) rather than pretending to restore a
    list it does not have. Totals will not match the historical 87/474; any comparison
    against pre-2026-09-10 numbers must be re-derived on this corpus, not assumed.

DEFLECTIONS
    Recovered from a surviving sample (L03_tri_prism_recon, diag 2.97 mm ->
    0.00149 / 0.00297 / 0.0099): fine = diag/2000, normal = diag/1000, coarse = diag/300.
    Verified against recorded triangle-count anchors by `verify_corpus.py`.

usage:  build_corpus.py [--out DIR] [--jobs N] [--only PATTERN]
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

HOME = Path.home()
ALPHA = HOME / "projects/cad-3d/reverse-engineering/alphaevolve/benchmark"
KICAD_GLOB = ".local/share/flatpak/runtime/org.kicad.KiCad.Library.Packages3D/x86_64/stable"

# --- SOURCES ---------------------------------------------------------------
# Each entry: (tag, list of source .step paths, which variants to emit).
# "normal" models get all three deflections; the KiCad negatives are used only at
# `fine`, which is how they were used historically (NEG_*_fine.stl).

def kicad_root() -> Path | None:
    base = HOME / KICAD_GLOB
    if not base.is_dir():
        return None
    for d in sorted(base.iterdir()):
        p = d / "files/3dmodels"
        if p.is_dir():
            return p
    return None


def sources() -> list[tuple[str, Path, tuple[str, ...]]]:
    """(output stem, source step, variants). Deterministic order."""
    out: list[tuple[str, Path, tuple[str, ...]]] = []
    tri = ("fine", "normal", "coarse")

    # 1. the alphaevolve benchmark: 100 designed parts + 100 reconstructions of them.
    for sub in ("step", "reconstructed"):
        d = ALPHA / sub
        if d.is_dir():
            for f in sorted(d.glob("*.step")):
                out.append((f.stem, f, tri))

    # 2. named extras that were in the corpus and live in their own projects.
    for p in (
        HOME / "projects/orca-cad-primitives/resources/calib/volumetric_speed/SpeedTestStructure.step",
        HOME / "projects/cad-3d/freecad-mcp/assets/gancio_zanza/gancio_parametric.step",
        HOME / "projects/stampa-3d/pipeline/3dprint-pipeline/clamp_half_a.step",
    ):
        if p.is_file():
            out.append((p.stem, p, tri))

    # 3. the designed-polygon NEGATIVES.
    #    RULE (this is the manifest decision, finally made explicit): the negative set is
    #    the whole Package_TO_SOT_SMD family. It is a coherent, named KiCad family and it
    #    contains all four CAD-verified sentinels (SC-59, SOT-143R, TSOT-23, SuperSOT-3),
    #    whose truth counts are the gate this corpus exists to protect. A rule beats a
    #    list nobody can reproduce.
    k = kicad_root()
    if k:
        fam = k / "Package_TO_SOT_SMD.3dshapes"
        if fam.is_dir():
            for f in sorted(fam.glob("*.step")):
                out.append((f"NEG_{f.stem}", f, ("fine",)))
    return out


# --- one model -------------------------------------------------------------

def build_one(stem: str, src: str, variants: tuple[str, ...], outdir: str) -> dict:
    """Tessellate + count. Runs in a worker process; imports OCP lazily."""
    from OCP.BRep import BRep_Tool
    from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
    from OCP.BRepBndLib import BRepBndLib
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.Bnd import Bnd_Box
    from OCP.GeomAbs import GeomAbs_Circle, GeomAbs_Cylinder, GeomAbs_Plane
    from OCP.STEPControl import STEPControl_Reader
    from OCP.StlAPI import StlAPI_Writer
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS

    rec: dict = {"name": stem, "src": src}
    r = STEPControl_Reader()
    if r.ReadFile(src) != 1:
        return {**rec, "error": "ReadFile failed"}
    r.TransferRoots()
    shape = r.OneShape()
    if shape.IsNull():
        return {**rec, "error": "null shape"}

    bb = Bnd_Box()
    BRepBndLib.Add_s(shape, bb)
    if bb.IsVoid():
        return {**rec, "error": "void bbox"}
    xm, ym, zm, xM, yM, zM = bb.Get()
    diag = math.sqrt((xM - xm) ** 2 + (yM - ym) ** 2 + (zM - zm) ** 2)
    if not (diag > 0):
        return {**rec, "error": "degenerate bbox"}

    # --- truth, counted on the SOURCE B-Rep (not on the mesh, not by hand)
    n_cyl = n_pln = n_oth = 0
    cyl_radii: list[float] = []
    ex = TopExp_Explorer(shape, TopAbs_FACE)
    while ex.More():
        s = BRepAdaptor_Surface(TopoDS.Face_s(ex.Current()))
        t = s.GetType()
        if t == GeomAbs_Cylinder:
            n_cyl += 1
            cyl_radii.append(round(s.Cylinder().Radius(), 6))
        elif t == GeomAbs_Plane:
            n_pln += 1
        else:
            n_oth += 1
        ex.Next()

    n_circ = 0
    circ_radii: list[float] = []
    ex = TopExp_Explorer(shape, TopAbs_EDGE)
    while ex.More():
        c = BRepAdaptor_Curve(TopoDS.Edge_s(ex.Current()))
        if c.GetType() == GeomAbs_Circle:
            n_circ += 1
            circ_radii.append(round(c.Circle().Radius(), 6))
        ex.Next()

    rec.update(diag_mm=round(diag, 4), faces=n_cyl + n_pln + n_oth, cyl_faces=n_cyl,
               planar_faces=n_pln, other_faces=n_oth, circle_edges=n_circ,
               cyl_radii=sorted(set(cyl_radii)), circ_radii=sorted(set(circ_radii)))

    # --- meshes. Divisor recovered from a surviving sample; see module docstring.
    div = {"fine": 2000.0, "normal": 1000.0, "coarse": 300.0}
    rec["stl"] = {}
    for v in variants:
        defl = diag / div[v]
        path = Path(outdir) / f"{stem}_{v}.stl"
        try:
            # A fresh read per variant: BRepMesh caches its triangulation on the shape,
            # so meshing the same TopoDS at a second deflection silently keeps the first.
            rr = STEPControl_Reader()
            rr.ReadFile(src)
            rr.TransferRoots()
            sh = rr.OneShape()
            BRepMesh_IncrementalMesh(sh, defl, False, 0.5, True)
            w = StlAPI_Writer()
            w.ASCIIMode = False
            if not w.Write(sh, str(path)):
                rec["stl"][v] = {"error": "write failed"}
                continue
            rec["stl"][v] = {"path": str(path), "deflection": round(defl, 6),
                             "bytes": path.stat().st_size,
                             "triangles": (path.stat().st_size - 84) // 50}
        except Exception as e:  # noqa: BLE001 - one bad source must not kill the corpus
            rec["stl"][v] = {"error": f"{type(e).__name__}: {e}"}
    return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HOME / "corpora/cadbench"))
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 4) // 2))
    ap.add_argument("--only", default=None, help="substring filter on the output stem")
    a = ap.parse_args()

    outdir = Path(a.out)
    outdir.mkdir(parents=True, exist_ok=True)
    src = sources()
    if a.only:
        src = [s for s in src if a.only in s[0]]
    if not src:
        print("no sources found -- check the paths in sources()", file=sys.stderr)
        return 2
    print(f"{len(src)} sources -> {outdir}  ({a.jobs} workers)", flush=True)

    truth: dict[str, dict] = {}
    errors = 0
    with ProcessPoolExecutor(max_workers=a.jobs) as pool:
        futs = {pool.submit(build_one, stem, str(p), v, str(outdir)): stem
                for stem, p, v in src}
        for i, f in enumerate(as_completed(futs), 1):
            rec = f.result()
            if "error" in rec:
                errors += 1
                print(f"  [{i}/{len(src)}] ERROR {rec['name']}: {rec['error']}", flush=True)
            else:
                truth[rec.pop("name")] = rec
            if i % 25 == 0:
                print(f"  [{i}/{len(src)}] ...", flush=True)

    tp = outdir / "truth.json"
    tp.write_text(json.dumps(dict(sorted(truth.items())), indent=1))
    tot_cyl = sum(v["cyl_faces"] for v in truth.values())
    withcyl = sum(1 for v in truth.values() if v["cyl_faces"])
    print(f"\nwrote {tp}\n  models {len(truth)} (errors {errors})"
          f"\n  models with cylinders {withcyl}\n  truth cylinder faces {tot_cyl}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
