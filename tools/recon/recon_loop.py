#!/usr/bin/env python3
"""Measure -> the model writes a CadQuery program -> execute -> gate -> feed back WHERE it is wrong.

No per-object-type code: the model sees the renders and the measured facts, and writes the
construction with the full CAD vocabulary (taper for draft, fillets, chamfers, revolves, holes,
patterns). Code never supplies a construction strategy; the model never supplies a number that is
not in the facts. The gate is the same for every part.
usage: recon_loop.py <stl> <facts.json> <render_dir> <workdir> [model=opus] [iters=4]
"""
import json, os, subprocess, sys, textwrap, time
from pathlib import Path
import numpy as np
import trimesh

SHIM = str(Path(__file__).resolve().parent)        # cqshim.py lives next to this file

_pr = None  # set in main()

REPAIR_DIR = str(Path(__file__).resolve().parents[1] / "feature_recon")


def invalid_face_report(shape, limit=10):
    """Why BRepCheck says this solid is invalid: each bad face's surface type, area and bbox centre."""
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepBndLib import BRepBndLib
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.BRepGProp import BRepGProp
    from OCP.Bnd import Bnd_Box
    from OCP.GProp import GProp_GProps
    from OCP.GeomAbs import (GeomAbs_BSplineSurface, GeomAbs_Cone, GeomAbs_Cylinder,
                             GeomAbs_Plane, GeomAbs_Sphere, GeomAbs_Torus)
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS
    kinds = {GeomAbs_Plane: "plane", GeomAbs_Cylinder: "cylinder", GeomAbs_Cone: "cone",
             GeomAbs_Torus: "torus", GeomAbs_Sphere: "sphere", GeomAbs_BSplineSurface: "bspline"}
    out = []
    ex = TopExp_Explorer(shape, TopAbs_FACE)
    while ex.More() and len(out) < limit:
        face = TopoDS.Face_s(ex.Current())
        ex.Next()
        try:
            if BRepCheck_Analyzer(face).IsValid():
                continue
            g = GProp_GProps(); BRepGProp.SurfaceProperties_s(face, g)
            bb = Bnd_Box(); BRepBndLib.Add_s(face, bb)
            xmin, ymin, zmin, xmax, ymax, zmax = bb.Get()
            out.append({"type": kinds.get(BRepAdaptor_Surface(face).GetType(), "other"),
                        "area": float(g.Mass()),
                        "centre": [float((xmin + xmax) / 2), float((ymin + ymax) / 2), float((zmin + zmax) / 2)]})
        except Exception:  # noqa: BLE001 - one bad face must not abort the report
            continue
    return out


def try_repair(shape):
    """Run the deterministic repair on an invalid shape; report whether the result is valid."""
    from OCP.BRepCheck import BRepCheck_Analyzer
    try:
        if BRepCheck_Analyzer(shape).IsValid():
            return shape, False
        if REPAIR_DIR not in sys.path:
            sys.path.insert(0, REPAIR_DIR)
        from auto25g import repair_step_shape
        out = repair_step_shape(shape)
        if isinstance(out, tuple):
            out = out[0]
        if BRepCheck_Analyzer(out).IsValid():
            return out, True
        return shape, False
    except Exception:  # noqa: BLE001 - a failed repair must not abort the loop
        return shape, False


def represent_detail(stl, step, samples=12):
    """patch_representation.represent(), same counts, plus location of every patch NOT represented."""
    tri = _pr._mesh(Path(stl))
    lo, hi = tri.reshape(-1, 3).min(0), tri.reshape(-1, 3).max(0)
    tol = _pr.TOL_REL * float(np.linalg.norm(hi - lo))
    _, groups = _pr.model_faces(Path(step))
    out = {"patches": 0, "curved": 0, "plane": 0, "other": 0, "far": 0, "misses": []}
    if not groups:
        return out
    curved = {k: v for k, v in groups.items() if k in _pr.ANALYTIC}
    nonan = {k: v for k, v in groups.items() if k not in _pr.ANALYTIC and k != "plane"}
    patches = _pr.mesh_patches(tri)
    out["patches"] = len(patches)
    for radius, idx in patches:
        pts = tri[list(idx)].mean(axis=1) if idx is not None else tri.mean(axis=1)
        pick = pts[np.linspace(0, len(pts) - 1, min(samples, len(pts))).astype(int)]
        dc = min((np.percentile([_pr._dist(q, c) for q in pick], 95) for c in curved.values()), default=float("inf"))
        dp = np.percentile([_pr._dist(q, groups["plane"]) for q in pick], 95) if "plane" in groups else float("inf")
        do = min((np.percentile([_pr._dist(q, c) for q in pick], 95) for c in nonan.values()), default=float("inf"))
        if dc <= tol and dc <= dp and dc <= do:
            out["curved"] += 1; continue
        kind = "other" if (do <= tol and do <= dp) else ("plane" if dp <= tol else "far")
        out[kind] += 1
        c = pts.mean(0); ext = np.ptp(pts, 0)
        what = {"plane": "your solid has a PLANE there (modelled flat or as a sharp edge?)",
                "other": "your solid has a NON-ANALYTIC (spline) face there - use an exact cylinder/cone/torus",
                "far": "your solid has NO surface near it"}[kind]
        out["misses"].append(f"cylindrical mesh patch r={radius:.3f} mm centred near ({c[0]:.2f}, {c[1]:.2f}, {c[2]:.2f}) "
                             f"spanning {ext[0]:.1f} x {ext[1]:.1f} x {ext[2]:.1f} mm: {what}")
    return out


def select_best(history, diag):
    """Pick the round the product is judged on: fidelity to the mesh first, most curved features second.

    Only valid rounds compete; a round more than 0.5% of the part diagonal off is disqualified from
    winning on feature count (an 8 mm-off round with the most features must never win). If no round
    is within the bound, the least-off valid round wins. No valid round -> None.
    """
    valid = [h for h in history if isinstance(h.get("report"), dict) and h["report"].get("valid") is True]
    if not valid:
        return None
    bound = 0.005 * diag

    def err(h):
        r = h["report"]
        return max(r["p95_mesh_to_solid"], r["p95_solid_to_mesh"])

    within = [h for h in valid if err(h) <= bound]
    if within:
        return max(within, key=lambda h: (h["report"]["features"]["curved"], -err(h)))
    return min(valid, key=err)


def _is_limit(text):
    t = (text or "").lower()
    return any(s in t for s in ("usage limit", "rate limit", "rate_limit", "overloaded", "429", "quota"))


def run_script(py, step):
    code = f"import sys; sys.path.insert(0, {SHIM!r}); import cqshim, cadquery as cq\n" + open(py).read() + \
           f"\ncq.exporters.export(result, {str(step)!r})\n"
    p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=600)
    return p.returncode == 0 and Path(step).exists(), (p.stderr or "")[-1500:]


def _descendants(root):
    kids = {}
    for d in os.listdir("/proc"):
        if d.isdigit():
            try:
                ppid = int(open(f"/proc/{d}/stat").read().rsplit(")", 1)[1].split()[1])
            except (OSError, IndexError, ValueError):
                continue
            kids.setdefault(ppid, []).append(int(d))
    out, todo = [], [root]
    while todo:
        for c in kids.get(todo.pop(), []):
            out.append(c); todo.append(c)
    return out


def ask_model(prompt, claude, model, wd, renders=()):
    if model.startswith("opencode:"):
        name = model.split(":", 1)[1]
        cmd = [os.environ.get("OPENCODE_BIN", "opencode"), "run", "-m", name]
        if "vision" in name:                       # only a vision model can see the renders
            for r in renders:
                cmd += ["-f", r]
        cmd.append(prompt)
    else:
        name = model.split(":", 1)[1] if model.startswith("claude:") else model
        cmd = [claude, "-p", "--model", name, "--allowedTools", "Read,Write",
               "--output-format", "text", prompt]
    t = float(os.environ.get("RECON_CALL_TIMEOUT_S", "1800"))
    # same process group as the loop, so a caller killing the loop's group reaches the model call too
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=str(wd))
    try:
        out, _ = p.communicate(timeout=t)
    except subprocess.TimeoutExpired:            # a hung call costs its round, never the run
        for pid in _descendants(p.pid) + [p.pid]:   # snap opencode escapes its cgroup: kill the tree
            try:
                os.kill(pid, 9)
            except ProcessLookupError:
                pass
        p.wait()
        return 124, f"model call timed out after {t:.0f} s"
    return p.returncode, (out or "")[-2000:]


def write_best(history, diag, wd):
    """(Re)write best.step/best.json from the history so far; None when no round is valid."""
    best = select_best(history, diag)
    if best is None:
        return None
    import shutil
    src = Path(best["py"]).with_suffix(".step")
    if best["report"].get("repaired"):          # the round's measurements are the repaired solid's
        src = src.with_name(src.stem + ".repaired.step")
    shutil.copy(src, wd / "best.step.tmp"); os.replace(wd / "best.step.tmp", wd / "best.step")
    json.dump({"best": best["py"], "report": best["report"], "represent": best["report"]["features"]},
              open(wd / "best.json.tmp", "w"), indent=1)
    os.replace(wd / "best.json.tmp", wd / "best.json")
    return best


def main():
    global _pr
    if len(sys.argv) < 5:
        print("usage: recon_loop.py <stl> <facts.json> <render_dir> <workdir> [model=opus] [iters=4]")
        return 2
    # absolute: the model CLI runs with cwd=WD, so relative paths in its prompt/-f resolve wrongly
    STL, FACTS, RDIR, WD = (os.path.abspath(a) for a in sys.argv[1:5])
    MODEL = sys.argv[5] if len(sys.argv) > 5 else "opus"
    ITERS = int(sys.argv[6]) if len(sys.argv) > 6 else 4
    WD = Path(WD); WD.mkdir(parents=True, exist_ok=True)
    CLAUDE = os.environ.get("CLAUDE_BIN", "/home/tommaso/.local/bin/claude")
    BACKOFF = float(os.environ.get("RECON_BACKOFF_S", "600"))
    QUOTA_RETRIES = int(os.environ.get("RECON_QUOTA_RETRIES", "3"))

    ns = {}
    exec(open(Path(__file__).parent / "shape_check.py").read().split("mesh = trimesh.load")[0], ns)  # step_mesh()
    step_mesh = ns["step_mesh"]
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
    import patch_representation as _pr  # noqa: F811

    mesh = trimesh.load(STL, force="mesh")
    diag = float(np.linalg.norm(mesh.bounds[1] - mesh.bounds[0]))
    renders = sorted(str(p) for p in Path(RDIR).glob("*.png"))

    def gate(step):
        from OCP.STEPControl import STEPControl_Reader, STEPControl_Writer, STEPControl_AsIs
        from OCP.BRepCheck import BRepCheck_Analyzer
        from OCP.GProp import GProp_GProps
        from OCP.BRepGProp import BRepGProp

        def measure(p):
            r = STEPControl_Reader(); r.ReadFile(str(p)); r.TransferRoots(); sh = r.OneShape()
            g = GProp_GProps(); BRepGProp.VolumeProperties_s(sh, g)
            t = open(p, errors="replace").read()
            solid = step_mesh(str(p))
            pm, _ = trimesh.sample.sample_surface(mesh, 20000, seed=0)
            ps, _ = trimesh.sample.sample_surface(solid, 20000, seed=0)
            d_ms = np.abs(trimesh.proximity.closest_point(solid, pm)[1])     # mesh not covered = missing
            d_sm = np.abs(trimesh.proximity.closest_point(mesh, ps)[1])      # solid not on mesh = extra
            rep = {"valid": bool(BRepCheck_Analyzer(sh).IsValid()),
                   "volume_delta_pct": round(100 * (g.Mass() - mesh.volume) / mesh.volume, 3),
                   "faces": t.count("ADVANCED_FACE"), "cylinders": t.count("CYLINDRICAL_SURFACE"),
                   "cones": t.count("CONICAL_SURFACE"), "tori": t.count("TOROIDAL_SURFACE"),
                   "planes": t.count("= PLANE("), "bsplines": t.count("B_SPLINE_SURFACE"),
                   "p95_mesh_to_solid": round(float(np.percentile(d_ms, 95)), 4),
                   "p95_solid_to_mesh": round(float(np.percentile(d_sm, 95)), 4),
                   "max_mesh_to_solid": round(float(d_ms.max()), 3), "max_solid_to_mesh": round(float(d_sm.max()), 3),
                   "pct_mesh_off_0.1mm": round(100 * float(np.mean(d_ms > 0.1)), 2),
                   "pct_solid_off_0.1mm": round(100 * float(np.mean(d_sm > 0.1)), 2)}

            def where(pts, d, label):
                far = pts[d > 0.1]
                if len(far) == 0:
                    return []
                # cluster the misses coarsely on a 10 mm grid and report the biggest clusters with location
                key = np.floor(far / 10.0).astype(int)
                u, inv, cnt = np.unique(key, axis=0, return_inverse=True, return_counts=True)
                out = []
                for i in np.argsort(-cnt)[:6]:
                    P = far[inv.ravel() == i]; D = d[d > 0.1][inv.ravel() == i]
                    out.append(f"{label}: {cnt[i]} samples near x={P[:,0].mean():.1f} y={P[:,1].mean():.1f} "
                               f"z={P[:,2].mean():.1f} (z {P[:,2].min():.1f}..{P[:,2].max():.1f}), off by up to {D.max():.2f} mm")
                return out
            rep["where_wrong"] = where(pm, d_ms, "MESH SURFACE NOT COVERED by your solid") + \
                                 where(ps, d_sm, "YOUR SOLID HAS SURFACE WHERE THE MESH HAS NONE")
            f = represent_detail(STL, p)
            rep["features"] = {k: f[k] for k in ("patches", "curved", "plane", "other", "far")}
            rep["feature_misses"] = f["misses"][:15]
            return rep, sh

        rep, sh = measure(step)
        if rep["valid"]:
            rep["repaired"] = False
            return rep
        repaired, did = try_repair(sh)
        if did:
            rstep = step.with_name(step.stem + ".repaired.step")
            w = STEPControl_Writer(); w.Transfer(repaired, STEPControl_AsIs); w.Write(str(rstep))
            rep, _ = measure(rstep)
            rep["repaired"] = True
            return rep
        rep["repaired"] = False
        rep["invalid_faces"] = invalid_face_report(sh)
        return rep

    if MODEL.startswith("opencode:"):
        _name = MODEL.split(":", 1)[1]
        if "vision" in _name:
            look = "First LOOK at the renders (they are attached to this message):\n" + "\n".join(renders)
        else:
            look = ("The renders are unavailable to you; the measured facts are complete and are "
                    "your only input.")
    else:
        look = "First LOOK at the renders (use the Read tool on each):\n" + "\n".join(renders)

    BRIEF = textwrap.dedent(f"""
    You are reverse-engineering a mechanical part from its mesh into parametric CAD, the way an
    experienced engineer would. {look}
    Then read the measured facts (Read tool): {FACTS}
    The facts are measured from the mesh and are the ONLY source of dimensions: slice levels along
    the axis, each loop fitted to exact lines and arcs with absolute coordinates, and the draft angle
    of every loop's wall (degrees; positive = the loop shrinks going up the axis). Do not invent
    dimensions; derive every number from the facts.

    Write a CadQuery (Python) program that builds the part as one solid in the SAME absolute
    coordinates as the facts, and assign it to a variable named `result`. `cadquery` is already
    imported as `cq`; do not import it and do not export anything. Use the construction an engineer
    would use: extrude profiles (use extrude(..., taper=deg) for drafted walls -- CadQuery's taper is
    positive inward), cut pockets and windows, fillet/chamfer where the profile shows arcs or bevels,
    revolve turned features, pattern repeated features. Prefer exact analytic geometry: lines, arcs,
    tapers -- never splines.
    """).strip()

    history = []
    if os.environ.get("RESUME"):          # continue a previous run: its rounds become our history
        history = json.load(open(os.environ["RESUME"]))
    start = len(history) + 1
    for it in range(start, start + ITERS):
        py = WD / f"recon_{it}.py"
        if not history:
            prompt = BRIEF + f"\n\nWrite the program to the file {py} with the Write tool. Reply only 'done'."
        else:
            prev = history[-1]
            prompt = BRIEF + textwrap.dedent(f"""

            Your previous program is {prev['py']} (read it). It was executed and measured against the mesh:
            {json.dumps(prev['report'], indent=1) if prev['report'] else 'IT FAILED TO RUN: ' + prev['error']}

            Fix what the measurement says is wrong -- the 'where_wrong' lines tell you where your solid
            misses mesh surface or adds surface the mesh does not have, and 'feature_misses' lists every
            cylindrical feature of the mesh that your solid does not reproduce as an exact analytic
            cylinder/cone/torus face (with its radius and location). If 'valid' is false, 'invalid_faces' lists the faces that make your solid invalid (type, area,
            location): rebuild those features so every face is valid. Every feature counts. Keep what is right. Write the
            corrected program to {py} with the Write tool. Reply only 'done'.""")
        _, out = ask_model(prompt, CLAUDE, MODEL, WD, renders)
        if not py.exists():
            if _is_limit(out):
                for _ in range(QUOTA_RETRIES):      # retries do not consume a round
                    time.sleep(BACKOFF)
                    _, out = ask_model(prompt, CLAUDE, MODEL, WD, renders)
                    if py.exists():
                        break
                if not py.exists():
                    print(f"iter {it}: model CLI usage/rate limit exhausted after {QUOTA_RETRIES} retries", flush=True)
                    history.append({"py": str(py), "report": None, "error": out})
                    json.dump(history, open(WD / "history.json", "w"), indent=1)
                    return 75
            else:
                print(f"iter {it}: model wrote no program: {out[-300:]}", flush=True)
                history.append({"py": str(py), "report": None, "error": out}); continue
        step = WD / f"recon_{it}.step"
        ok, err = run_script(py, step)
        rep = None
        if ok:
            try:
                rep = gate(step)
            except Exception as e:                  # e.g. a solid that tessellates to nothing
                ok, err = False, f"your program ran, but measuring its solid failed ({type(e).__name__}: {e}); " \
                                 "the result is probably empty or degenerate"
        history.append({"py": str(py), "report": rep, "error": err if not ok else ""})
        print(f"iter {it}: " + (json.dumps({k: v for k, v in rep.items() if k != 'where_wrong'}) if rep else "FAILED TO RUN: " + err[-300:]), flush=True)
        if rep:
            print(f"      features {rep['features']}", flush=True)
            json.dump(history, open(WD / "history.json", "w"), indent=1)
            write_best(history, diag, WD)          # a loop killed from outside keeps its best so far
            for w in rep["where_wrong"][:3] + rep["feature_misses"][:3]:
                print("      " + w, flush=True)
            fz = rep["features"]
            if (rep["valid"] and rep["p95_mesh_to_solid"] < 0.05 and rep["p95_solid_to_mesh"] < 0.05
                    and fz["curved"] == fz["patches"]):
                print(f"converged at iteration {it}"); break
    json.dump(history, open(WD / "history.json", "w"), indent=1)

    best = write_best(history, diag, WD)
    if best is None:
        return 2
    score = best["report"]["features"]
    print("BEST", best["py"], json.dumps({k: v for k, v in best["report"].items() if k != "where_wrong"}))
    print("REPRESENT", json.dumps(score))
    return 0


if __name__ == "__main__":
    sys.exit(main())
