"""Feature-level reconstruction: rebuild a mechanical part from its FEATURES (extrusion profiles,
stepped levels, turned envelopes, holes, slots, fillets measured from slices) and let it replace
the engine's output only where it is demonstrably better.

A candidate build replaces the engine STEP only if ALL hold:
  * one valid closed solid that survives a STEP round trip;
  * volume within MAX_DV_PCT, mesh->model p95 distance within MAX_DIST_P95_REL of the diagonal;
  * more cylindrical faces than the engine built;
  * at least MIN_SUPPORT of its cylinders have a radius the MESH itself shows as a cylinder
    (tools/feature_recon/quads.py: paired triangles -> quads -> normal lines meeting on an axis).
    Slicing a cone, sphere or smooth blend invents staircases of cylinders; those surfaces carry
    no quad cylinders, so the invented faces are unsupported (cadbench: <= 23.5% on every build
    that invented cylinders, >= 48% on 28 of 29 verified mechparts builds).

The builders are the tools/feature_recon prototypes, run as subprocesses: an OCCT crash or hang
costs that candidate, never the conversion.

usage: python3 -m mesh2step.feature <stl> -o <out.step> [engine args...]
           runs the native engine into <out.step>, then upgrades it if a feature build qualifies
       python3 -m mesh2step.feature <stl> -o <out.step> --no-fallback --engine-step <engine.step>
           feature build only; exit 3 if none qualifies
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

RECON = Path(__file__).resolve().parents[2] / "tools" / "feature_recon"
MAX_DV_PCT = 1.0
# mesh->model p95 distance as a share of the part diagonal. Volume alone cannot see a
# right-volume wrong-place build; the 29 FreeCAD-verified mechparts builds measure <= 0.42%.
MAX_DIST_P95_REL = 0.005
MIN_SUPPORT = 0.35
CANDIDATE_TIMEOUT_S = 1800.0


def _candidates(stl: Path, wd: Path):
    """(label, argv, env, output). The turned cut consumes the envelope, so order matters."""
    py = sys.executable
    c = [(f"extrude-{'xyz'[a]}", [py, RECON / "auto2d.py", stl, wd / f"A{a}.step"],
          {"AXIS": str(a)}, wd / f"A{a}.step") for a in range(3)]
    c.append(("stepped", [py, RECON / "auto25g.py", stl, wd / "B.step", "60"], {"AXIS": "2"},
              wd / "B.step"))
    c.append(("turned-envelope", [py, RECON / "autorev.py", stl, wd / "C.step", "400"], {},
              wd / "C.step"))
    c.append(("turned", [py, RECON / "autorev_cut4.py", stl, wd / "C.step", wd / "C4.step"], {},
              wd / "C4.step"))
    c.append(("block", [py, RECON / "autoblock2.py", stl, wd / "E.step"], {}, wd / "E.step"))
    return c


def _mesh(stl: Path) -> np.ndarray:
    from .io_mesh import load_mesh

    v, t = load_mesh(stl)
    return v[t]


def _read(step: Path):
    from OCP.STEPControl import STEPControl_Reader

    r = STEPControl_Reader()
    if r.ReadFile(str(step)) != 1:
        return None
    r.TransferRoots()
    return r.OneShape()


def cylinder_radii(shape) -> list[float]:
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Cylinder
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp
    from OCP.TopoDS import TopoDS
    from OCP.TopTools import TopTools_IndexedMapOfShape

    fm = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_FACE, fm)
    surfs = [BRepAdaptor_Surface(TopoDS.Face_s(fm.FindKey(i))) for i in range(1, fm.Extent() + 1)]
    return [s.Cylinder().Radius() for s in surfs if s.GetType() == GeomAbs_Cylinder]


def mesh_cylinder_radii(tri: np.ndarray) -> list[float]:
    """Radii of the cylinders the tessellation shows (quad strips, normals meeting on an axis)."""
    sys.path.insert(0, str(RECON))
    from quads import classify

    return [o[2] for o in classify(tri)[2] if o[0] == "cylinder"]


def support(built: list[float], mesh_radii: list[float]) -> float:
    if not built:
        return 1.0
    ok = sum(1 for x in built if any(abs(x - y) <= 0.03 * y + 0.05 for y in mesh_radii))
    return ok / len(built)


def measure(step: Path, tri: np.ndarray, samples: int = 300) -> dict | None:
    """Health of a written STEP against its mesh; None if it does not read."""
    from OCP.BRep import BRep_Builder, BRep_Tool
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    from OCP.BRepGProp import BRepGProp
    from OCP.GeomAbs import GeomAbs_Plane
    from OCP.gp import gp_Pnt
    from OCP.GProp import GProp_GProps
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_SOLID
    from OCP.TopExp import TopExp
    from OCP.TopoDS import TopoDS, TopoDS_Compound
    from OCP.TopTools import TopTools_IndexedDataMapOfShapeListOfShape, TopTools_IndexedMapOfShape

    sh = _read(step)
    if sh is None:
        return None
    sm = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(sh, TopAbs_SOLID, sm)
    fm = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(sh, TopAbs_FACE, fm)
    ef = TopTools_IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(sh, TopAbs_EDGE, TopAbs_FACE, ef)
    free = sum(1 for i in range(1, ef.Extent() + 1)
               if not BRep_Tool.Degenerated_s(TopoDS.Edge_s(ef.FindKey(i)))
               and ef.FindFromIndex(i).Extent() < 2)
    planes = sum(1 for i in range(1, fm.Extent() + 1)
                 if BRepAdaptor_Surface(TopoDS.Face_s(fm.FindKey(i))).GetType() == GeomAbs_Plane)
    g = GProp_GProps()
    BRepGProp.VolumeProperties_s(sh, g)
    mvol = float(np.einsum("ij,ij->i", tri[:, 0], np.cross(tri[:, 1], tri[:, 2])).sum() / 6.0)
    # mesh -> model surface distance on a fixed vertex sample (deterministic)
    comp = TopoDS_Compound()
    b = BRep_Builder()
    b.MakeCompound(comp)
    for i in range(1, fm.Extent() + 1):
        b.Add(comp, fm.FindKey(i))
    verts = np.unique(tri.reshape(-1, 3), axis=0)
    pick = verts[np.linspace(0, len(verts) - 1, min(samples, len(verts))).astype(int)]
    dd = []
    for p in pick:
        v = BRepBuilderAPI_MakeVertex(gp_Pnt(*map(float, p))).Vertex()
        ds = BRepExtrema_DistShapeShape(v, comp)
        ds.Perform()
        if ds.IsDone():
            dd.append(ds.Value())
    lo, hi = tri.reshape(-1, 3).min(0), tri.reshape(-1, 3).max(0)
    radii = cylinder_radii(sh)
    return {
        "solids": sm.Extent(), "faces": fm.Extent(), "free_edges": free,
        "valid": bool(BRepCheck_Analyzer(sh).IsValid()),
        "cylinders": len(radii), "radii": radii, "planes": planes,
        "volume": g.Mass(), "mesh_volume": mvol,
        "dv_pct": 100.0 * (g.Mass() - mvol) / mvol if mvol else float("inf"),
        "dist_p95": float(np.percentile(dd, 95)) if dd else float("inf"),
        "diag": float(np.linalg.norm(hi - lo)),
    }


def acceptable(m: dict | None) -> bool:
    """Shape gate only: one valid closed solid, close to the mesh in volume and surface."""
    return bool(m and m["solids"] == 1 and m["valid"] and m["free_edges"] == 0
                and abs(m["dv_pct"]) <= MAX_DV_PCT
                and m["dist_p95"] <= MAX_DIST_P95_REL * m["diag"])


def reconstruct(stl, out, *, min_cylinders: int = 0, timeout: float = CANDIDATE_TIMEOUT_S,
                log=None) -> dict | None:
    """Try every builder; keep the qualifying build closest to the mesh volume."""
    stl, out = Path(stl), Path(out)
    tri = _mesh(stl)
    mesh_radii = None
    best = None
    with tempfile.TemporaryDirectory(prefix="m2s_feature_") as td:
        wd = Path(td)
        for label, argv, env, produced in _candidates(stl, wd):
            try:
                subprocess.run([str(a) for a in argv], capture_output=True, timeout=timeout,
                               env=dict(os.environ, **env), cwd=td)
            except subprocess.TimeoutExpired:
                continue
            m = measure(produced, tri) if produced.exists() else None
            if acceptable(m) and m["cylinders"] > min_cylinders:
                if mesh_radii is None:
                    mesh_radii = mesh_cylinder_radii(tri)
                m["support"] = support(m["radii"], mesh_radii)
            if log:
                brief = {k: v for k, v in (m or {}).items() if k != "radii"}
                print(f"feature {label}: {brief}", file=log, flush=True)
            if (m and m.get("support", 0.0) >= MIN_SUPPORT
                    and (best is None or abs(m["dv_pct"]) < abs(best["dv_pct"]))):
                best = dict(m, method=label)
                shutil.copyfile(produced, wd / "best.step")
        if best:
            shutil.copyfile(wd / "best.step", out)
    return best


def native_payload(m: dict, stl, out, seconds: float) -> dict:
    """The accepted build in the native engine's RESULT shape, so every caller renders it."""
    return {
        "ok": True, "input": str(stl), "output": str(out), "solids": 1, "openShells": 0,
        "watertight": True, "freeEdges": 0, "stepVolumeMM3": m["volume"],
        "meshVolumeMM3": m["mesh_volume"], "volumeDeltaPct": m["dv_pct"],
        "facesBeforeUnify": m["faces"], "facesAfterUnify": m["faces"],
        "facesAfterSmooth": m["faces"], "smooth": True, "smoothPlanes": m["planes"],
        "smoothCylinders": m["cylinders"], "seconds": seconds, "warnings": [],
        # the webapp renders the BUILT counts (_native_stats reads smoothBuilt*); without them a served feature
        # build shows no cylinders at all, while an edgebuild result shows its 46
        "smoothBuiltPlanes": m["planes"], "smoothBuiltCylinders": m["cylinders"],
        "featureMethod": m["method"], "featureSupport": m["support"],
        "featureDistP95": m["dist_p95"],
    }


def _engine_cylinders(step: Path) -> int:
    sh = _read(step) if step.exists() else None
    return len(cylinder_radii(sh)) if sh is not None else 0


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    stl, out = Path(argv[0]), Path(argv[argv.index("-o") + 1])
    t0 = time.time()
    if "--no-fallback" in argv:
        engine = Path(argv[argv.index("--engine-step") + 1]) if "--engine-step" in argv else None
        n = _engine_cylinders(engine) if engine else 0
        m = reconstruct(stl, out, min_cylinders=n, log=sys.stderr)
        if not m:
            return 3
        print("RESULT " + json.dumps(native_payload(m, stl, out, time.time() - t0)))
        return 0

    from .native import native_binary

    proc = subprocess.run([str(native_binary()), *argv], capture_output=True, text=True)
    with tempfile.TemporaryDirectory(prefix="m2s_feature_out_") as td:
        cand = Path(td) / "feature.step"
        m = reconstruct(stl, cand, min_cylinders=_engine_cylinders(out), log=sys.stderr)
        if m:
            shutil.copyfile(cand, out)
            print("RESULT " + json.dumps(native_payload(m, stl, out, time.time() - t0)))
            return 0
    sys.stdout.write(proc.stdout)
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
