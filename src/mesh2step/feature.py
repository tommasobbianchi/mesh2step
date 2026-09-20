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
# The agent loop: a rejected candidate is repaired and re-measured rather than discarded.
# Bounded on both axes because runtime is already a product problem (mechparts/6 converts in
# 1968 s). Two attempts per candidate is enough for the only chain that exists -- drop the
# debris, then close the shell -- and the budget is wall clock for the WHOLE pass, checked
# before each repair so a long builder cannot be followed by an unbounded repair tail.
LOOP_MAX_ATTEMPTS = 2
LOOP_BUDGET_S = float(os.environ.get("MESH2STEP_LOOP_BUDGET_S", "240"))


# Backflip's "Thinking mode", with the same intent: when the shape is nearly right, spend more
# on the SAME construction instead of throwing it away. The knob is the builder's own sampling
# density -- `stepped` slices N heights to find its levels, `turned-envelope` takes N stations
# along the axis -- so a finer run is a better-measured build of the same kind, never a looser
# gate. The other builders expose no such knob and are not retried.
# label -> (index of the output path in argv, index of the density argument, denser value)
REFINE = {"stepped": (3, 4, "180"), "turned-envelope": (3, 4, "1200")}


def _refine_argv(label: str, argv: list, out):
    """argv for a denser re-run of this builder into `out`, or None if it has no knob."""
    spec = REFINE.get(label)
    if spec is None or len(argv) <= spec[1] or str(argv[spec[1]]) == spec[2]:
        return None
    a = list(argv)
    a[spec[0]], a[spec[1]] = out, spec[2]
    return a


def _worth_refining(m: dict | None, fails: list[str], min_cylinders: int) -> bool:
    """A shape near-miss on a build that actually recovered something.

    NOT a relaxation: the candidate is still rejected. It buys a second, denser attempt at the
    same construction, which must then pass the identical gate. Bounded to a near-miss because a
    build that is 500% out on volume is not nearly right, it is wrong.
    """
    return bool(m and fails and set(fails) <= {"dv_pct", "dist_p95"}
                and m["cylinders"] > min_cylinders
                and m["dist_p95"] <= 2.0 * MAX_DIST_P95_REL * m["diag"]
                and abs(m["dv_pct"]) <= 2.0 * MAX_DV_PCT)


# The immune system's SECOND opinion, for a rejection that names `support` and nothing else.
# `support` is a radius question -- does the mesh show a cylinder of this radius ANYWHERE -- and
# on mechparts/19 it scores 0.21 on a build that puts 17 of 17 mesh cylinder patches on analytic
# faces at 0.018 mm p95. `backing.backed_fraction` asks the location question instead: is there
# mesh wall at THIS face's axis, radius and extent, with a radial normal. It is not a looser
# test -- measured on the canonical confabulators it is far harsher than the radius test
# (L09_valve_body stepped 0.16, mechparts/19 stepped 0.13, mechparts/16 stepped 0.09, against a
# radius support of 0.19/0.01/0.05) -- and it is the positive evidence guideline 4.B.5 asks for.
# MIN_SUPPORT is unchanged and the shape gate must already have passed. `MESH2STEP_LOOP_BACKING=0`
# disables it independently of the rest of the loop.
def _second_opinion(m: dict, produced: Path, tri, log=None) -> float | None:
    """Backed fraction for a support-only rejection, or None if the check is off or throws."""
    if os.environ.get("MESH2STEP_LOOP_BACKING", "1") == "0":
        return None
    from .backing import backed_fraction

    try:
        sh = _read(produced)
        if sh is None:
            return None
        frac, n_backed, n_total = backed_fraction(sh, tri)
    except Exception as exc:  # noqa: BLE001
        if log:
            print(f"feature: backing check failed: {type(exc).__name__}: {exc}",
                  file=log, flush=True)
        return None
    if log:
        print(f"feature: backing {n_backed}/{n_total} = {frac:.2f} "
              f"(radius support {m['support']:.2f})", file=log, flush=True)
    return frac


def _repair_for(fails: list[str]):
    """(name, fn) for the first failed clause that names a repair of the SOLID, else None.

    `dv_pct` and `dist_p95` are deliberately absent: they are statements about the shape the
    builder chose, and the only honest repair is a different build, not a post-hoc edit. A
    candidate that fails only those is reported and dropped.
    """
    from . import solidfix

    for c in fails:
        if c == "solids":
            return ("largest", solidfix.largest_solid)
        if c in ("valid", "free_edges"):
            return ("sew", solidfix.sew_fix)
    return None

# Progress, not prediction. The candidate list is FIXED, so "step 4 of 8" is exact even though
# the duration is not: measured on 351 real conversions, the same mesh at the same triangle
# count spans 3 s to 900 s (webapp/server.py SRVCONV log), so no up-front number is honest.
# One JSON line per phase transition into $MESH2STEP_PHASE_LOG; the server tails the last line
# for /api/job and keeps the finished timings as the profile a future ETA can be fitted on.
def _phase(i: int, n: int, label: str, state: str, seconds: float | None = None) -> None:
    path = os.environ.get("MESH2STEP_PHASE_LOG")
    if not path:
        return
    rec = {"i": i, "n": n, "label": label, "state": state, "t": time.time()}
    if seconds is not None:
        rec["seconds"] = round(seconds, 3)
    try:
        with open(path, "a") as fh:
            fh.write(json.dumps(rec) + "\n")
    except OSError:
        pass  # progress reporting must never cost the conversion


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
    sh = r.OneShape()
    # A builder that writes a STEP carrying no transferable root leaves OneShape() NULL, not
    # empty: every OCCT call on it throws Standard_NullObject rather than returning nothing.
    # Measured 2026-09-19 on L10_idler_bracket, where that throw escaped reconstruct() and
    # destroyed an already-qualifying build that had recovered all 6 cylinders (bd projects-3md).
    return None if sh.IsNull() else sh


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


# Radius tolerance for calling a built cylinder the same cylinder as a reference one. Kept
# equal to scripts/radius_audit.py so the two never disagree about what "the same radius" means.
RADIUS_REL, RADIUS_ABS = 0.005, 1e-4


def pair_radii(built: list[float], want: list[float]) -> int:
    """Greedy ONE-TO-ONE matches between two radius multisets, largest first.

    Multiplicity is the whole point: four M3 holes are four cylinders, and a build that recovers
    one of them must not score four by matching the same radius over and over. A matched radius
    is still only an upper bound on recall -- the right radius in the wrong place counts.
    """
    pool = sorted(want, reverse=True)
    n = 0
    for r in sorted(built, reverse=True):
        for i, t in enumerate(pool):
            if abs(r - t) <= max(RADIUS_REL * t, RADIUS_ABS):
                pool.pop(i)
                n += 1
                break
    return n


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


# --- IP4: every candidate rejection names ONE clause -------------------------------------
# Acilindria-guideline.md 2.1: "A rejection that cannot be attributed to a named clause is
# itself a non-conformance: it makes the next session guess." The measurements already exist;
# only the naming was missing. Clause order is SEVERITY order, not gate order: the clause
# reported is the one whose repair is a prerequisite for the others (a build with 4 solids has
# a meaningless dv), so a reader can act on the first name without re-deriving the rest.
CLAUSES = ("no_output", "unreadable", "solids", "valid", "free_edges", "dv_pct", "dist_p95",
           "no_gain", "support")


def failures(m: dict | None, min_cylinders: int, sup: float | None) -> list[str]:
    """Every clause this candidate fails, in severity order. [] means it qualifies."""
    if m is None:
        return ["unreadable"]
    f = []
    if m["solids"] != 1:
        f.append("solids")
    if not m["valid"]:
        f.append("valid")
    if m["free_edges"]:
        f.append("free_edges")
    if abs(m["dv_pct"]) > MAX_DV_PCT:
        f.append("dv_pct")
    if m["dist_p95"] > MAX_DIST_P95_REL * m["diag"]:
        f.append("dist_p95")
    if m["cylinders"] <= min_cylinders:
        f.append("no_gain")
    if sup is not None and sup < MIN_SUPPORT:
        f.append("support")
    return f


def defect_code(m: dict | None, fails: list[str], sup: float | None,
                mesh_radii: list[float] | None) -> str:
    """The Acilindria defect code for this rejection (physiopathologia section 2).

    Coded from the FIRST failed clause, because that is the one whose repair the others wait on:
    a build with four solids has a meaningless volume, so calling it a support failure because
    support also failed would send the next session to the immune system for a carpentry defect.
    `AC-B4` therefore means what the text says -- passed every shape gate, refused for inventing.
    """
    if not fails:
        return "OK"
    if fails and fails[0] == "no_output":
        return "AC-NOBUILD"                  # this builder cannot model this part; not a defect
    if m is None:
        return "AC-C1"                       # wrote a file nothing can read
    head = fails[0]
    if head == "no_gain":
        return "AC-NOGAIN"                   # healthy: the engine already did better
    if head == "support":
        if mesh_radii is not None and not mesh_radii:
            return "AC-B5"                   # support undefined, not failed
        return "AC-B4"                       # correct immune rejection
    if head == "dist_p95" and m["dist_p95"] <= 2.0 * MAX_DIST_P95_REL * m["diag"]:
        return "AC-B3"                       # near-miss on a shape threshold
    return "AC-B2"                           # whole-build rejection over a defect of the solid


def reconstruct(stl, out, *, min_cylinders: int = 0, timeout: float = CANDIDATE_TIMEOUT_S,
                log=None) -> dict | None:
    """Try every builder; keep the qualifying build closest to the mesh volume.

    Two things happen here beyond the original one-shot pass, both new:

    * **IP4 attribution** (guideline 2.1). Every candidate, accepted or not, logs the clauses it
      failed and the Acilindria defect code. A rejection nobody can name is a non-conformance.
    * **The repair loop** (`MESH2STEP_LOOP=0` disables). When the named clause is a defect of the
      SOLID, the candidate is repaired and re-measured against the SAME gate, instead of being
      discarded with everything it recovered. Bounded by `LOOP_MAX_ATTEMPTS` per candidate and
      `LOOP_BUDGET_S` of wall clock for the whole pass, because runtime is already a product
      problem. The gate is never relaxed: `MIN_SUPPORT` and the mesh-backed radius test are
      applied to the repaired build exactly as to the original.
    """
    stl, out = Path(stl), Path(out)
    loop_on = os.environ.get("MESH2STEP_LOOP", "1") != "0"
    tri = _mesh(stl)
    cache: dict = {"mesh_radii": None}
    best = None
    phases: list[list] = []
    t_pass = time.time()

    def mesh_radii():
        if cache["mesh_radii"] is None:
            cache["mesh_radii"] = mesh_cylinder_radii(tri)
        return cache["mesh_radii"]

    def evaluate(produced: Path, label: str):
        """(measurement, failed clauses, support) for one written STEP. Never raises."""
        try:
            m = measure(produced, tri) if produced.exists() else None
        except Exception as exc:  # noqa: BLE001
            # The contract at the top of this file: an OCCT crash costs THAT CANDIDATE,
            # never the conversion. It held for the subprocess builders and not for the
            # in-process read of what they wrote, which is the half that actually threw.
            if log:
                print(f"feature {label}: measure failed: {type(exc).__name__}: {exc}",
                      file=log, flush=True)
            return None, ["unreadable"], None
        if m is None:
            return None, ["no_output" if not produced.exists() else "unreadable"], None
        sup = support(m["radii"], mesh_radii()) if m["cylinders"] else None
        m["support"] = 1.0 if sup is None else sup
        return m, failures(m, min_cylinders, sup), sup

    def report(label: str, m, fails, sup):
        if not log:
            return
        brief = {k: v for k, v in (m or {}).items() if k != "radii"}
        code = defect_code(m, fails, sup, cache["mesh_radii"])
        verdict = "ACCEPT" if not fails else f"REJECT {fails[0]} [{code}]"
        extra = f" also={fails[1:]}" if len(fails) > 1 else ""
        print(f"feature {label}: {verdict}{extra} {brief}", file=log, flush=True)

    with tempfile.TemporaryDirectory(prefix="m2s_feature_") as td:
        wd = Path(td)
        cands = _candidates(stl, wd)
        for i, (label, argv, env, produced) in enumerate(cands, 1):
            _phase(i, len(cands), label, "start")
            t_c = time.time()
            try:
                subprocess.run([str(a) for a in argv], capture_output=True, timeout=timeout,
                               env=dict(os.environ, **env), cwd=td)
            except subprocess.TimeoutExpired:
                _phase(i, len(cands), label, "timeout", time.time() - t_c)
                phases.append([label, round(time.time() - t_c, 3), "timeout"])
                if log:
                    print(f"feature {label}: REJECT timeout [AC-TIMEOUT]", file=log, flush=True)
                continue
            m, fails, sup = evaluate(produced, label)
            # closed AFTER measure(): the phase must account for every second the user waits,
            # or the elapsed times never add up to the wall clock an ETA is fitted against
            _phase(i, len(cands), label, "done", time.time() - t_c)
            phases.append([label, round(time.time() - t_c, 3), "done"])
            report(label, m, fails, sup)

            if loop_on and fails == ["support"]:
                # Shape is already sound; only the radius-based invention test says no. Ask the
                # mesh where the faces actually are before throwing the build away.
                frac = _second_opinion(m, produced, tri, log)
                if frac is not None and frac >= MIN_SUPPORT:
                    m["support"], m["support_kind"] = frac, "backed"
                    fails = []
                    report(f"{label}+backed", m, fails, frac)

            attempt, src, refined = 0, produced, False
            while (loop_on and fails and attempt < LOOP_MAX_ATTEMPTS
                   and time.time() - t_pass < LOOP_BUDGET_S):
                action = _repair_for(fails)
                if action is None:
                    # No repair of the carrier applies. If the shape is only a near-miss, buy
                    # one denser re-run of the same builder; otherwise this candidate is done.
                    rout = wd / f"{label}.refine.step"
                    rargv = (None if refined or not _worth_refining(m, fails, min_cylinders)
                             else _refine_argv(label.split("+")[0], argv, rout))
                    if rargv is None:
                        break
                    refined, attempt = True, attempt + 1
                    left = LOOP_BUDGET_S - (time.time() - t_pass)
                    t_r = time.time()
                    try:
                        subprocess.run([str(a) for a in rargv], capture_output=True,
                                       timeout=min(timeout, max(left, 30.0)),
                                       env=dict(os.environ, **env), cwd=td)
                    except subprocess.TimeoutExpired:
                        if log:
                            print(f"feature {label}+refine: timeout", file=log, flush=True)
                        break
                    rlabel = f"{label}+refine"
                    m, fails, sup = evaluate(rout, rlabel)
                    phases.append([rlabel, round(time.time() - t_r, 3), "refine"])
                    report(rlabel, m, fails, sup)
                    src, label = rout, rlabel
                    continue
                attempt += 1
                fixed = wd / f"{label}.fix{attempt}.step"
                t_r = time.time()
                try:
                    done = action[1](src, fixed)
                except Exception as exc:  # noqa: BLE001
                    if log:
                        print(f"feature {label}: repair {action[0]} threw "
                              f"{type(exc).__name__}: {exc}", file=log, flush=True)
                    break
                if not done:
                    if log:
                        print(f"feature {label}: repair {action[0]} no-op", file=log, flush=True)
                    break
                rlabel = f"{label}+{action[0]}"
                m, fails, sup = evaluate(fixed, rlabel)
                phases.append([rlabel, round(time.time() - t_r, 3), "repair"])
                report(rlabel, m, fails, sup)
                src, label = fixed, rlabel

            if not fails and m is not None and "+" in label and "+backed" not in label:
                # A candidate the BASE arm would have thrown away is admitted only if the mesh
                # carries wall at each built face, not merely a matching radius somewhere.
                # Measured on mechparts/4: the denser `stepped` re-run passes the radius test at
                # 0.35+ and puts 4 of 28 patches on curved faces while building 46 cylinders of
                # which the mesh backs 7. That is the confabulation the guideline ranks worse
                # than the disease (0.3.1), so the loop refuses its own win.
                frac = _second_opinion(m, src, tri, log)
                if frac is not None and frac < MIN_SUPPORT:
                    fails = ["support"]
                    report(f"{label}+unbacked", m, fails, frac)

            if not fails and m is not None:
                if best is None or abs(m["dv_pct"]) < abs(best["dv_pct"]):
                    best = dict(m, method=label)
                    shutil.copyfile(src, wd / "best.step")
        if best:
            shutil.copyfile(wd / "best.step", out)
    if best is not None:
        best["phases"] = phases
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
        # per-candidate wall time: the only data that can ever calibrate an ETA
        "featurePhases": m.get("phases", []),
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
