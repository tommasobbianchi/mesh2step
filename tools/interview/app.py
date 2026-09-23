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
RUNS = REPO / "runs" / "interview"            # nativedev, project dir; runs/ is excluded from git
CLAUDE = os.path.expanduser("~/.local/bin/claude")
MODEL = os.environ.get("INTERVIEW_MODEL", "sonnet")
MAX_REGIONS = 40
SESS: dict = {}
app = FastAPI()

SYSTEM = """You interview the OWNER of a physical part, by voice, for about 5 minutes. You see the part only as its
3D mesh, summarised as REGIONS: areas bounded by sharp edges (kind plane / cylinder / curved, area, size, centre,
normal or axis, radius). The goal: learn the design intent so the part can be rebuilt as editable CAD.

How to run the interview:
- Start with what the whole part is and what it does.
- Check the real size: the mesh has no reliable units. If the bounding box looks implausible for the part they
  describe, ask them to measure one obvious feature (you highlight it) and record "scale" = real_mm / mesh_units.
- Then go area by area, most important first: HIGHLIGHT one region and ask "what is this, what does it do?".
  Ask for a measurement only where it matters (holes and shafts, thin walls, fits, how far something protrudes).
  Ask about standard parts (screws, bearings, magnets), symmetry and repeated features, what mates with what.
- One short question per turn, spoken style (it is read aloud): at most two sentences, no lists, no markdown.
- Speak the language the owner speaks (default English). Read back numbers you record ("eight millimetres, got it").
- After about 10 questions, or when the owner says they are done, give a one-sentence summary and set done=true.

Reply with ONLY a JSON object, nothing else:
{"say": "<what you say aloud>", "lang": "<BCP-47 like en-US or it-IT>", "highlight": [<region ids>],
 "record": {"<short key>": "<value with unit>"}, "done": false}
`record` holds only facts established in THIS turn (may be empty). `highlight` is the region(s) you ask about."""


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
    order = np.argsort(-tot)[:MAX_REGIONS]
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
                r.update(kind="cylinder", axis=np.round(axis, 3).tolist(), radius=round(rad, 3))
            else:
                r["kind"] = "curved"
        out.append(r)
    return face_region, out


def ask(s: dict, text: str) -> dict:
    cmd = [CLAUDE, "-p", "--tools", "", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
           "--model", MODEL, "--output-format", "json"]
    cmd += ["--resume", s["claude"]] if s.get("claude") else ["--system-prompt", SYSTEM]
    r = subprocess.run(cmd + [text], capture_output=True, text=True, timeout=180, cwd=s["dir"])
    d = json.loads(r.stdout)
    s["claude"] = d.get("session_id") or s.get("claude")
    s["cost"] = max(s.get("cost", 0), d.get("total_cost_usd") or 0)   # a resumed session reports its running total
    raw = (d.get("result") or "").strip()
    try:
        rep = json.loads(raw[raw.index("{"): raw.rindex("}") + 1])
    except ValueError:
        rep = {"say": raw, "highlight": [], "record": {}, "done": False}
    s["facts"].update(rep.get("record") or {})
    s["log"].append({"t": time.time(), "owner": text, **rep})
    (Path(s["dir"]) / "transcript.json").write_text(json.dumps(
        {"facts": s["facts"], "log": s["log"], "cost_usd": round(s["cost"], 3)}, indent=1))
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
    s = SESS[sid] = {"dir": str(d), "facts": {}, "log": [], "name": file.filename, "regions": regs}
    (d / "regions.json").write_text(json.dumps(regs))
    bb = np.round(m.extents, 3).tolist()
    rep = ask(s, f"The owner uploaded '{file.filename}'. Mesh bounding box {bb} (mesh units, maybe not mm), "
                 f"{len(m.faces)} triangles, watertight={m.is_watertight}. Regions:\n{json.dumps(regs)}\n"
                 "Greet them in one sentence and ask your first question.")
    return {"sid": sid, "stl_b64": base64.b64encode(m.export(file_type="stl")).decode(),
            "face_region": face_region.tolist(), "regions": regs, "reply": rep, "facts": s["facts"]}


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
    return {"heard": text, "reply": rep, "facts": s["facts"]}


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
    if kind == "stl" and (Path(SESS[sid]["dir"]) / "result.stl").exists():
        return FileResponse(Path(SESS[sid]["dir"]) / "result.stl")
    raise HTTPException(404, "no result yet")
