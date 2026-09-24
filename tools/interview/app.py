"""PRIVATE preview: a ~5-minute voice interview about a mesh, then an AI rebuild that uses the answers.

Mesh in -> regions (areas bounded by sharp edges) -> the interviewer highlights one region at a time and asks
what it is / what it does / a measurement where it matters -> notes -> recon_part.py with RECON_OWNER_NOTES.
Bind to 127.0.0.1 only; reach it through `tailscale serve` (tailnet, HTTPS: the browser needs it for the mic).
run: uvicorn app:app --host 127.0.0.1 --port 20011   (from tools/interview)
"""
import base64
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

import numpy as np
import trimesh
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "tools" / "tree"))
import fcstd as FC                                    # noqa: E402
import fix as FX                                      # noqa: E402
import propose as PR                                  # noqa: E402
import tree as T                                      # noqa: E402
RUNS = REPO / "runs" / "interview"            # nativedev, project dir; runs/ is excluded from git
CLAUDE = os.path.expanduser("~/.local/bin/claude")
MODEL = os.environ.get("INTERVIEW_MODEL", "sonnet")
MAX_REGIONS = 40
SESS: dict = {}
app = FastAPI()

SYSTEM = """You help the OWNER of a part confirm HOW IT IS BUILT, by voice, in a few turns. The part may be a
download with no physical object: never ask for measurements, never ask about micro details (screw sizes, fits).

A deterministic analysis has ALREADY proposed the construction as a feature tree (sketch -> extrude -> modify:
pads, pockets, holes, rounds, chamfers; ids F1, F2, ...) and measured how much of the mesh it explains. You get the
steps, the match, and where it misses. Your job is to get the STRUCTURE right, cheaply:
- First turn: say in one or two sentences how you read the part ("a plate extruded 6 units, a cross hole, chamfered
  rims; it matches 99.9 percent"), highlighting the features, and ask if that is how they would model it.
- The "misses" are hints, not features: a miss whose max_dist is under about 3x the tolerance is surface noise or a
  slightly-off round, never a ledge, step or groove. Do not invent features from them; mention a miss only when it
  is large (a whole missing boss, hole or cut).
- Then only what is uncertain: a poor match somewhere, or a feature whose role is ambiguous. Ask yes/no or
  "which of these", highlighting it. Never make the owner describe geometry you already have.
- When the owner corrects the structure ("the ring and the tail are separate extrusions", "that is a slot, not two
  holes", "mirror it") or the match is poor where they point, write ONE precise instruction for the tree editor in
  "fix" (it edits the tree; you will be told the new steps and match). Otherwise leave "fix" empty.
- At most 4 questions. When the owner agrees, or says done, one-sentence summary and done=true.
- Spoken style, at most two sentences, no lists or markdown. Speak the owner's language (default English).

Reply with ONLY a JSON object:
{"say": "<spoken>", "lang": "<BCP-47>", "highlight": ["F1", ...], "record": {"<key>": "<value>"}, "fix": "", "done": false}"""


def regions(m: trimesh.Trimesh):
    """Faces grouped across smooth edges (< 25 deg): each group is an area a person can name."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    n = len(m.faces)
    adj = m.face_adjacency[m.face_adjacency_angles < np.radians(25)]
    g = coo_matrix((np.ones(len(adj)), (adj[:, 0], adj[:, 1])), shape=(n, n))
    _, lab = connected_components(g, directed=False)
    area = m.area_faces
    tot = np.bincount(lab, weights=area)
    order = [c for c in np.argsort(-tot) if tot[c] > 0][:MAX_REGIONS]   # degenerate (zero-area) slivers name nothing
    face_region = np.full(n, -1, dtype=int)
    out = []
    for rid, comp in enumerate(order):
        idx = np.where(lab == comp)[0]
        face_region[idx] = rid
        nrm = m.face_normals[idx]; w = area[idx]
        c = np.average(m.triangles_center[idx], axis=0, weights=w)
        pts = m.triangles_center[idx]
        mean_n = np.average(nrm, axis=0, weights=w)
        r = {"id": rid, "area": round(float(w.sum()), 2), "center": np.round(c, 2).tolist(),
             "size": np.round(np.ptp(m.vertices[m.faces[idx].ravel()], axis=0), 2).tolist()}
        if np.linalg.norm(mean_n) > 0.995:
            r.update(kind="plane", normal=np.round(mean_n / np.linalg.norm(mean_n), 3).tolist())
        else:
            axis = np.linalg.svd(nrm * w[:, None], full_matrices=False)[2][-1]   # normals of a cylinder are _|_ axis
            if np.abs(nrm @ axis).max() < 0.15:
                u = np.cross(axis, [1, 0, 0] if abs(axis[0]) < 0.9 else [0, 1, 0]); u /= np.linalg.norm(u)
                v = np.cross(axis, u); p = np.c_[pts @ u, pts @ v]
                A = np.c_[2 * p, np.ones(len(p))]; b = (p ** 2).sum(1)                # Kasa circle fit
                sol = np.linalg.lstsq(A, b, rcond=None)[0]
                rad = float(np.sqrt(max(sol[2] + sol[0] ** 2 + sol[1] ** 2, 0)))
                ctr = sol[0] * u + sol[1] * v + float((pts @ axis).mean()) * axis           # on the axis, mid-height
                r.update(kind="cylinder", axis=np.round(axis, 3).tolist(), radius=round(rad, 3),
                         axis_point=np.round(ctr, 3).tolist(), u=np.round(u, 3).tolist())
            else:
                r["kind"] = "curved"
        out.append(r)
    return face_region, out


def _runs(loop: np.ndarray, span: float, n: int = 720):
    """A closed 2D section loop cut into runs of constant curvature: ("arc", r, centre, sweep_deg, pts) or ("line", pts).
    Works on filleted meshes, where no edge is sharp and region growing sees one smooth surface."""
    seg = np.r_[0, np.cumsum(np.linalg.norm(np.diff(loop, axis=0), axis=1))]
    t = np.linspace(0, seg[-1], n, endpoint=False)
    p = np.c_[np.interp(t, seg, loop[:, 0]), np.interp(t, seg, loop[:, 1])]
    a, c = np.roll(p, 4, 0), np.roll(p, -4, 0)
    u, v, w = p - a, c - p, c - a
    curv = 2 * (u[:, 0] * v[:, 1] - u[:, 1] * v[:, 0]) / np.maximum(
        np.linalg.norm(u, axis=1) * np.linalg.norm(v, axis=1) * np.linalg.norm(w, axis=1), 1e-12)
    straight = np.abs(curv) * span < 0.5
    lab = np.sign(curv) * np.log(np.maximum(np.abs(curv), 1e-9))
    brk = [i for i in range(n) if straight[i] != straight[i - 1] or (not straight[i] and abs(lab[i] - lab[i - 1]) > 0.25)] or [0]
    out = []
    for j, s0 in enumerate(brk):
        e = brk[(j + 1) % len(brk)]
        q = p[np.arange(s0, e if e > s0 else e + n) % n]
        if len(q) < 6:
            continue
        if straight[s0]:
            out.append(("line", q))
            continue
        sol = np.linalg.lstsq(np.c_[2 * q, np.ones(len(q))], (q ** 2).sum(1), rcond=None)[0]   # Kasa circle fit
        r = float(np.sqrt(max(sol[2] + sol[0] ** 2 + sol[1] ** 2, 0)))
        if r > 0:
            out.append(("arc", r, sol[:2], np.degrees(len(q) * seg[-1] / n / r), q))
    return out


def dims(m: trimesh.Trimesh, regs: list) -> list:
    """Dimensions drawn on the model for the owner to type over: overall lengths, main diameters, wall thicknesses.
    Diameters/walls come first from the mid cross-section across the extrusion axis (the sketch), then from regions."""
    (x0, y0, z0), (x1, y1, z1) = m.bounds
    out = [{"id": "L" + a, "label": a, "value": float(b - c), "a": pa, "b": pb}
           for a, b, c, pa, pb in (("X", x1, x0, [x0, y0, z0], [x1, y0, z0]), ("Y", y1, y0, [x1, y0, z0], [x1, y1, z0]),
                                   ("Z", z1, z0, [x1, y0, z0], [x1, y0, z1]))]
    span = float(max(m.extents))
    dia, wall = [], []                               # (value, a, b, region|None)
    n, w = m.face_normals, m.area_faces
    cands = list(np.linalg.eigh((n * w[:, None]).T @ n)[1].T) + list(np.eye(3))
    score = [w[(np.abs(n @ e) < 0.05) | (np.abs(n @ e) > 0.995)].sum() / w.sum() for e in cands]
    if max(score) > 0.8:                             # an extrusion: walls parallel to e, caps across it
        e = cands[int(np.argmax(score))]
        h = m.vertices @ e
        sec = m.section(plane_origin=e * (h.min() + h.max()) / 2, plane_normal=e)
        if sec is not None:
            pl, T = sec.to_2D()
            to3 = lambda q: (T @ np.r_[q[0], q[1], 0, 1])[:3].tolist()
            arcs, lines = [], []
            for loop in pl.discrete:
                for x in _runs(np.asarray(loop), span):
                    (arcs if x[0] == "arc" else lines).append(x)
            for _, r, c, sweep, q in sorted(arcs, key=lambda x: -x[1]):
                if sweep >= 150:                     # a hole or a C/round end; fillets sweep ~90 and are micro detail
                    ang = 0.6 + 0.9 * len(dia)       # concentric diameters drawn at different angles, labels apart
                    u = r * np.array([np.cos(ang), np.sin(ang)])
                    dia.append((2 * r, to3(c - u), to3(c + u), None))
            big = [x for x in arcs if x[3] >= 150]
            for i, (_, r1, c1, _, q1) in enumerate(big):          # concentric arcs: the wall between them
                for _, r2, c2, _, _ in big[i + 1:]:
                    if np.linalg.norm(c1 - c2) < 0.02 * span and abs(r1 - r2) > 1e-3 * span:
                        d = q1[len(q1) // 2] - c1; d /= np.linalg.norm(d)
                        wall.append((abs(r1 - r2), to3(c1 + d * r1), to3(c1 + d * r2), None))
            for i, q1 in enumerate(lines):                        # parallel opposite straight runs: a plate or rib
                d1 = q1[1][-1] - q1[1][0]; l1 = np.linalg.norm(d1)
                for q2 in lines[i + 1:]:
                    d2 = q2[1][-1] - q2[1][0]; l2 = np.linalg.norm(d2)
                    if min(l1, l2) < 0.1 * span or abs(d1 @ d2) < 0.99 * l1 * l2:
                        continue
                    m1 = q1[1].mean(0); gap = q2[1].mean(0) - m1
                    t = abs(d1[0] * gap[1] - d1[1] * gap[0]) / l1
                    if 0 < t < 0.5 * span and abs(gap @ d1) / l1 < 0.5 * (l1 + l2):
                        nrm = np.array([-d1[1], d1[0]]) / l1 * np.sign(d1[0] * gap[1] - d1[1] * gap[0])
                        wall.append((t, to3(m1), to3(m1 + nrm * t), None))
    for r in sorted((r for r in regs if r["kind"] == "cylinder"), key=lambda r: -r["area"]):
        c, u = np.array(r["axis_point"]), np.array(r["u"]) * r["radius"]
        dia.append((2 * r["radius"], (c - u).tolist(), (c + u).tolist(), r["id"]))
    planes = sorted((r for r in regs if r["kind"] == "plane"), key=lambda r: -r["area"])[:12]
    for p in planes:                                 # a thickness: the nearest opposite-facing face behind a big face
        nn, c = np.array(p["normal"]), np.array(p["center"])
        gaps = [g for q in planes if np.dot(q["normal"], nn) < -0.98
                for g in [float((c - np.array(q["center"])) @ nn)] if 0 < g < 0.5 * span]
        if gaps:
            wall.append((min(gaps), c.tolist(), (c - nn * min(gaps)).tolist(), p["id"]))
    for tag, label, items, cap, seen in (("D", "\u2300", dia, 5, []), ("T", "t", wall, 4, [float(x) for x in m.extents])):
        k = 0
        for v, a, b, rid in items:                   # one label per distinct size; an overall length is not a wall
            if v > 0 and all(abs(v - q) > 0.03 * q for q in seen) and k < cap:
                seen.append(v); k += 1
                out.append({"id": f"{tag}{k}", "label": label, "value": v, "a": a, "b": b,
                            **({"region": rid} if rid is not None else {})})
    for x in out:
        x["value"] = round(float(x["value"]), 4)
    return out


def ask(s: dict, text: str) -> dict:
    if s.get("typed"):                              # sizes the owner typed on the model since the last turn
        text = f"(The owner typed on the model: {'; '.join(s.pop('typed'))}. scale is now {s['facts'].get('scale')}.) " + text
    cmd = [CLAUDE, "-p", "--tools", "", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
           "--model", MODEL, "--output-format", "json"]
    cmd += ["--resume", s["claude"]] if s.get("claude") else ["--system-prompt", SYSTEM]
    r = subprocess.run(cmd + [text], capture_output=True, text=True, timeout=180, cwd=s["dir"])
    d = json.loads(r.stdout)
    s["claude"] = d.get("session_id") or s.get("claude")
    costs = s.setdefault("costs", {})                 # per source; a resumed session reports its running total
    costs["interview"] = max(costs.get("interview", 0), d.get("total_cost_usd") or 0)
    raw = (d.get("result") or "").strip()
    try:
        rep = json.loads(raw[raw.index("{"): raw.rindex("}") + 1])
    except ValueError:
        rep = {"say": raw, "highlight": [], "record": {}, "done": False}
    s["facts"].update(rep.get("record") or {})
    s["log"].append({"t": time.time(), "owner": text, **rep})
    (Path(s["dir"]) / "transcript.json").write_text(json.dumps(
        {"facts": s["facts"], "log": s["log"], "costs": costs, "cost_usd": round(sum(costs.values()), 3)}, indent=1))
    return rep


_whisper = None


def transcribe(path: str) -> str:
    global _whisper
    if _whisper is None:
        from faster_whisper import WhisperModel
        _whisper = WhisperModel("small", device="cpu", compute_type="int8")
    segs, _ = _whisper.transcribe(path, vad_filter=True)
    return " ".join(x.text.strip() for x in segs).strip()


@app.get("/")
def index():
    return FileResponse(HERE / "index.html")


@app.post("/api/start")
def start(file: UploadFile = File(...)):
    sid = uuid.uuid4().hex[:12]
    d = RUNS / sid; d.mkdir(parents=True)
    mesh = d / "mesh.stl"
    suffix = Path(file.filename or "x.stl").suffix.lower()
    raw = d / f"upload{suffix}"; raw.write_bytes(file.file.read())
    m = trimesh.load(raw, force="mesh"); m.export(mesh)
    face_region, regs = regions(m)
    s = SESS[sid] = {"dir": str(d), "facts": {}, "log": [], "name": file.filename, "regions": regs,
                     "dims": dims(m, regs), "measured": {}}
    (d / "regions.json").write_text(json.dumps(regs))
    s["status"] = "analysing"
    threading.Thread(target=_analyse, args=(sid,), daemon=True).start()
    return {"sid": sid, "stl_b64": base64.b64encode(m.export(file_type="stl")).decode(),
            "face_region": face_region.tolist(), "regions": regs, "dims": s["dims"], "facts": s["facts"]}


def steps(tree):
    """The tree in words, one line per feature: what the owner hears about and the interviewer reads."""
    out = []
    for f in tree["features"]:
        if f["op"] in ("pad", "pocket"):
            kinds = [x["t"] for lp in f["loops"] for x in lp]
            k0 = [x["t"] for x in f["loops"][0]]
            shp = ("circle \u2300%.3g" % (2 * f["loops"][0][0]["r"]) if k0 == ["circle"] else
                   f"outline of {k0.count('line')} lines and {k0.count('arc')} arcs")
            shp = (shp
                   + (f", {len(f['loops']) - 1} holes" if len(f["loops"]) > 1 else ""))
            L = f["length"]
            ext = "through all" if L == "through" else f"{abs(float(L)):.4g} along {'-' if float(L) < 0 else '+'}{f['axis']}"
            txt = f"sketch ({shp}) on the plane across {f['axis']} at {f['at']:.4g}, {'extruded' if f['op'] == 'pad' else 'cut'} {ext}"
        else:
            txt = f"{f['op']} {float(f['size']):.3g} on the {f.get('cap', 'both')} {f.get('loops', 'outer')} edges of {f['on']}"
        out.append({"id": f["id"], "label": f.get("label", f["id"]), "text": txt})
    return out


def _b64(a, dtype):
    return base64.b64encode(np.asarray(a).astype(dtype).tobytes()).decode()


def _refresh(s):
    """Compile the session's tree, measure it against the mesh, and cache what the page draws."""
    m, tol, tree = s["mesh"], s["tol"], s["tree"]
    shape, notes = T.compile_tree(tree, tol)
    dev = T.deviation(m, shape, tol)
    owner = T.feature_faces(m, tree, shape, tol)
    V, F = dev["solid_mesh"].vertices, dev["solid_mesh"].faces
    (Path(s["dir"]) / "tree.json").write_text(json.dumps(tree, indent=1))
    s["view"] = {"steps": steps(tree), "notes": notes, "explained": round(dev["explained"], 4),
                 "extra": round(dev["extra"], 4), "tol": round(tol, 4),
                 "face_err": _b64(np.clip(dev["face_dist"] / tol * 64, 0, 255), np.uint8),   # 64 = at tolerance
                 "face_feature": _b64(owner, np.int16),
                 "solid_stl": base64.b64encode(trimesh.Trimesh(V, F, process=False).export(file_type="stl")).decode()}
    s["evidence"] = FX.clusters(m, dev, tol, k=5)
    return s["view"]


def _analyse(sid):
    s = SESS[sid]
    try:
        d = Path(s["dir"]); an = d / "analysis"
        # its own process, memory-capped: OCCT on a bad sketch can take tens of GB (measured 44 GB once)
        subprocess.run(["systemd-run", "--user", "--scope", "--quiet", "--collect", "-p", "MemoryMax=8G",
                        "-p", "MemorySwapMax=0", sys.executable, str(REPO / "tools/tree/analyse.py"),
                        str(d / "mesh.stl"), str(an)], capture_output=True, text=True, timeout=1800)
        if not (an / "tree.json").exists():
            raise RuntimeError("the analysis did not finish (memory cap or timeout)")
        tree = json.loads((an / "tree.json").read_text()); info = json.loads((an / "analysis.json").read_text())
        m = trimesh.load(d / "mesh.stl", force="mesh")
        s.update(tree=tree, mesh=m, tol=info["tol"], analysis=info)
        s.setdefault("costs", {})["planner"] = info.get("cost_usd", 0)
        v = _refresh(s)
        bb = np.round(m.extents, 3).tolist()
        s["reply"] = ask(s, f"The owner uploaded '{s['name']}'. Mesh bounding box {bb} (units probably mm). "
                            f"Proposed construction:\n{json.dumps(v['steps'])}\nMatch: {v['explained']:.1%} of the "
                            f"mesh explained within {tol:.3g}; where it misses: {json.dumps(s['evidence'])}\n"
                            "Greet them in one sentence and read the construction back.")
        s["status"] = "ready"
    except Exception as e:                             # noqa: BLE001 -- shown to the tester as-is
        s["status"] = "failed"; s["error"] = f"{type(e).__name__}: {e}"[:300]


@app.get("/api/state/{sid}")
def state(sid: str):
    s = SESS.get(sid)
    if s is None:
        raise HTTPException(404, "unknown session")
    if s["status"] != "ready":
        return {"status": s["status"], "error": s.get("error")}
    return {"status": "ready", "view": s["view"], "reply": s.get("reply"), "facts": s["facts"],
            "analysis": s.get("analysis")}


@app.post("/api/dim")
def dim(sid: str = Form(...), id: str = Form(...), mm: float = Form(...)):
    """The owner typed a real size over a drawn dimension: it fixes the scale (median over all typed ones)."""
    s = SESS.get(sid)
    dm = next((x for x in (s or {}).get("dims", []) if x["id"] == id), None)
    if dm is None or not 0 < mm < 1e5 or dm["value"] <= 0:
        raise HTTPException(400, "bad dimension")
    s["measured"][id] = mm
    k = float(np.median([v / next(x["value"] for x in s["dims"] if x["id"] == i) for i, v in s["measured"].items()]))
    name = {"D": "diameter", "T": "thickness"}.get(id[0], "overall " + dm["label"]) + f" {id}"
    s["facts"]["scale"] = f"{k:.6g}"
    s["facts"][name] = f"{mm:g} mm (typed)"
    s.setdefault("typed", []).append(f"{name} = {mm:g} mm")
    return {"facts": s["facts"], "measured": s["measured"]}


@app.post("/api/turn")
def turn(sid: str = Form(...), text: str = Form(""), audio: UploadFile | None = File(None)):
    s = SESS.get(sid)
    if s is None:
        raise HTTPException(404, "unknown session")
    if audio is not None:
        with tempfile.NamedTemporaryFile(suffix=".webm", dir=s["dir"], delete=False) as fh:
            fh.write(audio.file.read())
        text = transcribe(fh.name)
    if not text:
        return {"heard": "", "reply": {"say": "Sorry, I didn't catch that.", "highlight": [], "record": {}}}
    rep = ask(s, text)
    out = {"heard": text, "reply": rep, "facts": s["facts"]}
    if (rep.get("fix") or "").strip() and s.get("tree"):
        new, ev, s["fix_sid"], c = FX.fix(s["tree"], s["mesh"], s["tol"], rep["fix"], s.get("fix_sid"), cwd=s["dir"])
        s.setdefault("costs", {})["fix"] = c           # the fixer session's running total
        if new is not None:
            s["tree"] = new; v = _refresh(s)
            out["view"] = v
            rep2 = ask(s, f"(The tree editor applied: {rep['fix']}. New steps: {json.dumps(v['steps'])}. "
                          f"Match {v['explained']:.1%}; misses: {json.dumps(s['evidence'])}.) Tell the owner what "
                          "changed in one sentence and ask if it is right now.")
            out["reply"] = rep2
        else:
            out["reply"]["say"] = (rep.get("say") or "") + " I could not apply that change; let's try it another way."
    return out


def _export(sid):
    s = SESS[sid]; d = Path(s["dir"])
    s["export"] = {"status": "running"}
    try:
        k = 1.0
        try:
            k = float(str(s["facts"].get("scale") or 1).split()[0])
        except ValueError:
            pass
        tree = scale_tree(s["tree"], k)
        (d / "final_tree.json").write_text(json.dumps(tree, indent=1))
        shape, _ = T.compile_tree(tree, s["tol"] * k)
        T.write_step(shape, d / "part.step")
        r = FC.build(tree, d / "part.FCStd", s["tol"] * k)
        s["export"] = {"status": "done", "scale": k, "fcstd_ok": bool(r.get("ok") and r.get("valid")),
                       "edit_breaks": r.get("edit_breaks"), "params": r.get("params"), "symdiff": r.get("symdiff"),
                       "error": r.get("error")}
    except Exception as e:                             # noqa: BLE001
        s["export"] = {"status": "failed", "error": f"{type(e).__name__}: {e}"[:300]}


def scale_tree(tree, k):
    """Every length in the tree times k (the owner's scale; 1 when the mesh is already in mm)."""
    t = json.loads(json.dumps(tree))
    if k == 1.0:
        return t
    sc = lambda p: [x * k for x in p]
    for f in t["features"]:
        for key in ("at", "size"):
            if key in f:
                f[key] = f[key] * k
        if f.get("length") not in (None, "through"):
            f["length"] = float(f["length"]) * k
        for lp in f.get("loops", []):
            for e in lp:
                if "p" in e:
                    e["p"] = [sc(q) for q in e["p"]]
                if "c" in e:
                    e["c"] = sc(e["c"]); e["r"] = e["r"] * k
    return t


@app.post("/api/export")
def export(sid: str = Form(...)):
    s = SESS.get(sid)
    if s is None or not s.get("tree"):
        raise HTTPException(404, "nothing to export yet")
    if (s.get("export") or {}).get("status") != "running":
        threading.Thread(target=_export, args=(sid,), daemon=True).start()
    return {"status": "running"}


@app.get("/api/export/{sid}")
def export_status(sid: str):
    return (SESS.get(sid) or {}).get("export") or {"status": "none"}


def _build(sid: str):
    s = SESS[sid]; d = Path(s["dir"])
    s["build"] = {"status": "running", "t0": time.time()}
    try:
        stl = d / "mesh.stl"
        scale = s["facts"].get("scale")
        try:
            k = float(str(scale).split()[0]) if scale else 1.0
        except ValueError:
            k = 1.0
        if k != 1.0:                                  # the owner's measurement fixed the units
            m = trimesh.load(stl); m.apply_scale(k); stl = d / "mesh_mm.stl"; m.export(stl)
        notes = d / "owner_notes.md"
        notes.write_text("Facts: " + json.dumps(s["facts"], ensure_ascii=False) + "\n\nInterview:\n" + "\n".join(
            f"- Q: {e.get('say')}\n  A: {e.get('owner')}" for e in s["log"][1:]) +
            ("\n(The mesh was scaled by the owner's measurement; coordinates are now mm.)" if k != 1.0 else ""))
        wd = d / "recon"
        cmd = ["systemd-run", "--user", "--scope", "--quiet", "--collect", "-p", "MemoryMax=8G",
               "-p", "MemorySwapMax=0", sys.executable, str(REPO / "tools/recon/recon_part.py"), str(stl), str(wd),
               "--models", "opus", "--rounds", "5", "--timeout", "3600"]
        subprocess.run(cmd, capture_output=True, text=True, timeout=4200,
                       env=dict(os.environ, RECON_OWNER_NOTES=str(notes)))
        res = json.loads((wd / "recon_result.json").read_text())
        step = res.get("best_step")
        if not step:
            raise RuntimeError(f"no result ({res.get('status')})")
        from OCP.STEPControl import STEPControl_Reader
        from OCP.BRepMesh import BRepMesh_IncrementalMesh
        from OCP.StlAPI import StlAPI_Writer
        rd = STEPControl_Reader(); rd.ReadFile(step); rd.TransferRoots(); sh = rd.OneShape()
        BRepMesh_IncrementalMesh(sh, 0.05, False, 0.3, True); StlAPI_Writer().Write(sh, str(d / "result.stl"))
        s["build"] = {"status": res["status"], "step": step, "represent": res.get("represent"),
                      "seconds": res.get("seconds"), "scale": k}
    except Exception as e:                        # noqa: BLE001 -- shown to the tester as-is
        s["build"] = {"status": "failed", "error": str(e)[:300]}


@app.post("/api/build")
def build(sid: str = Form(...)):
    if sid not in SESS:
        raise HTTPException(404, "unknown session")
    if (SESS[sid].get("build") or {}).get("status") == "running":
        return SESS[sid]["build"]
    threading.Thread(target=_build, args=(sid,), daemon=True).start()
    return {"status": "running"}


@app.get("/api/build/{sid}")
def build_status(sid: str):
    b = (SESS.get(sid) or {}).get("build") or {"status": "none"}
    return {k: v for k, v in b.items() if k != "step"}


@app.get("/api/result/{sid}/{kind}")
def result(sid: str, kind: str):
    b = (SESS.get(sid) or {}).get("build") or {}
    if kind == "step" and b.get("step"):
        return FileResponse(b["step"], filename=Path(SESS[sid]["name"]).stem + ".step")
    if kind in ("part.step", "part.FCStd") and (Path(SESS[sid]["dir"]) / kind).exists():
        return FileResponse(Path(SESS[sid]["dir"]) / kind, filename=Path(SESS[sid]["name"]).stem + kind[4:])
    if kind == "stl" and (Path(SESS[sid]["dir"]) / "result.stl").exists():
        return FileResponse(Path(SESS[sid]["dir"]) / "result.stl")
    raise HTTPException(404, "no result yet")
