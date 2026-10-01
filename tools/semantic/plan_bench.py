"""S2 bake-off: an LLM turns the S1 notes into a deconstruction Plan, scored against the owner's 5/5 trees. No build.

Input per part: the per-view notes of the chosen S1 (qwen3.8:27b, whole views + mid-plane cuts) and the S0 frame
(bounding box per world axis). Output: the Plan, undo order first (finishes -> cuts -> additions -> base sketch), every
sketch as named shapes, proportions instead of numbers, and the probes it needs.

Scored on structure only (numbers are S3's job): base extrusion axis, base outline class, revolve used, additive
feature count +-1, hole count +-1, fillets, chamfers present, and whether the undo order obeys the owner's sequence.

usage: plan_bench.py <out_dir> <model> [part ...]      model: qwen27b | qwen27b-nothink | deepseek | sonnet"""
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import trimesh

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vlm_bench as VB  # noqa: E402
from truth import GRADES, is_circle_loop  # noqa: E402

NOTES = Path(__file__).resolve().parents[2] / "runs/semantic/m1qs/qwen27b_g1_sect"
# PLAN_FACTS=1: edge fillets/chamfers are not the planner's to decide. S1's merge already answers them from the cuts
# under the evidence rule (20/28, 23/28); the planners re-deciding them did worse (Sonnet 17, 16).
FACTS = os.environ.get("PLAN_FACTS") == "1"
MERGED = NOTES.with_name(NOTES.name + "_v3")
CLAUDE = {"haiku": "claude-haiku-4-5-20251001", "sonnet": "claude-sonnet-5"}
CLAUDE_BIN = shutil.which("claude") or str(Path.home() / ".local/bin/claude")   # job units have no ~/.local/bin on PATH

P_PLAN = """You are a senior mechanical designer. Below are notes another model wrote while looking at ONE part: six
orthographic views, an isometric view, and cuts through the part's mid-planes. The notes can be wrong or contradict
each other; when views disagree, trust the cuts for edges and thickness, and the view looking straight at a face for
its outline. World axes: X, Y, Z as named in the notes. Bounding box (mm): {bbox}.

Reconstruct how a designer modelled it, by UNDOING the features in this order:
1. finishes: edge fillets, edge chamfers (only if the cuts along the thickness show rounded or bevelled corners);
2. subtractive features: holes, pockets, slots, cuts, revolved cuts;
3. additive features: bosses, ribs, extra extruded levels, revolved bodies;
4. the base body, down to its sketch.
Do no arithmetic. Describe sketches with this vocabulary only: circle, rectangle, rounded rectangle, slot, regular
polygon, polyline, polyline with arcs; relations: concentric, symmetric about, tangent, equal, linear pattern, circular
pattern, mirror. Give sizes as proportions of the bounding box or of other features.

Answer ONLY with this JSON:
{{"part_type": "<a few words>",
 "undo": [{{"step": 1, "stage": "finish|subtractive|additive", "op": "fillet|chamfer|hole|pocket|slot|cut|revolved cut|pad|boss|rib|revolve",
           "what": "<which feature>", "count": <integer>, "sketch": "<shape from the vocabulary, or null>",
           "relation": "<relation, or null>", "proportion": "<e.g. diameter ~0.2 x width>"}}],
 "base": {{"op": "extrude|revolve", "axis": "X|Y|Z (extrusion direction, or revolution axis)",
          "outline": "<shape from the vocabulary>", "inner_loops": [{{"shape": "<shape>", "count": <integer>}}],
          "proportion": "<thickness vs extent>"}},
 "holes_total": <total number of distinct holes in the finished part>,
 "probes": ["<parameter that needs a measurement, e.g. 'bore diameter'>"],
 "unsure": ["<what you could not tell>"]}}

{facts}NOTES:
{notes}"""

STAGE = {"finish": 0, "subtractive": 1, "additive": 2}
POLY = {"rectangle", "regular polygon", "polyline"}
ARCS = {"rounded rectangle", "slot", "polyline with arcs"}


def frame(part):
    m = trimesh.load(str(VB.MESHES / f"{part}.stl"), force="mesh")
    e = m.bounds[1] - m.bounds[0]
    return ", ".join(f"{a} {v:.1f}" for a, v in zip("XYZ", e))


def ask_llm(model, prompt):
    if model in CLAUDE:
        r = subprocess.run([CLAUDE_BIN, "-p", "--model", CLAUDE[model], "--tools", "", "--strict-mcp-config",
                            "--setting-sources", "", "--output-format", "json"],
                           input=prompt, capture_output=True, text=True, timeout=900)
        d = json.loads(r.stdout)
        return d["result"], {"usd": d.get("total_cost_usd", 0), "out": d.get("usage", {}).get("output_tokens", 0)}
    if model.startswith("qwen27b"):
        body = {"model": "qwen3.8:27b", "messages": [{"role": "user", "content": prompt}], "stream": False,
                "think": False if model.endswith("nothink") else "medium", "format": "json",
                "options": {"temperature": 0, "num_ctx": 32768}}
        req = urllib.request.Request(os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434") + "/api/chat",
                                     data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=1800) as r:
            j = json.loads(r.read())
        return j["message"]["content"], {"in": j.get("prompt_eval_count", 0), "out": j.get("eval_count", 0)}
    return VB.ask("deepseek", [], prompt, want_json=True)


def tree_facts(tree):
    """The structure of the owner's tree that a Plan must reproduce."""
    F = tree["features"]
    b = F[0]
    loop0 = b["loops"][0] if isinstance(b.get("loops"), list) and b["loops"] else []
    if len(loop0) == 1 and loop0[0]["t"] == "circle":
        outline = "circle"
    else:
        outline = "arcs" if any(g["t"] == "arc" for g in loop0) else "polygon"
    holes = sum(1 for f in F if f["op"] in ("pad", "pocket") and isinstance(f.get("loops"), list)
                for i, lp in enumerate(f["loops"]) if is_circle_loop(lp)
                and (i > 0 or f["op"] == "pocket"))
    return {"axis": b.get("axis"), "outline": outline, "revolve": any("revolve" in f for f in F),
            "additive": sum(f["op"] == "pad" for f in F), "holes": holes,
            "fillets": any(f["op"] == "round" for f in F), "chamfers": any(f["op"] == "chamfer" for f in F)}


def truth():
    out = {}
    for g in GRADES.glob("*.json"):
        d = json.load(open(g))
        if d.get("reviewer") == "tommaso" and d.get("overall") == 5 and Path(d["tree_file"]).exists():
            out[d["part"]] = tree_facts(json.load(open(d["tree_file"])))
    return out


def outline_class(s):
    s = (s or "").lower().strip()
    if s == "circle":
        return "circle"
    return "arcs" if s in ARCS or "arc" in s or "round" in s or "slot" in s else "polygon" if s in POLY or s else None


def score(plan, t):
    if not plan:
        return {"parsed": False}
    undo, base = plan.get("undo") or [], plan.get("base") or {}
    ops = [str(u.get("op", "")).lower() for u in undo]
    n = lambda u: int(u.get("count") or 1) if str(u.get("count", 1)).isdigit() else 1  # noqa: E731
    additive = 1 + sum(n(u) for u in undo if u.get("stage") == "additive")
    stages = [STAGE.get(u.get("stage"), -1) for u in undo]
    try:
        holes = int(plan.get("holes_total"))
    except (TypeError, ValueError):
        holes = -99
    return {"parsed": True,
            "axis": str(base.get("axis", "")).upper()[:1] == t["axis"],
            "outline": outline_class(base.get("outline")) == t["outline"],
            "revolve": (base.get("op") == "revolve" or any("revolve" in o for o in ops)) == t["revolve"],
            "additive_pm1": abs(additive - t["additive"]) <= 1,
            "holes_pm1": abs(holes - t["holes"]) <= 1,
            "fillets": ("fillet" in ops) == t["fillets"],
            "chamfers": ("chamfer" in ops) == t["chamfers"],
            "order": -1 not in stages and stages == sorted(stages)}


KEYS = ["axis", "outline", "revolve", "additive_pm1", "holes_pm1", "fillets", "chamfers", "order"]


def run(out, model, part, T):
    f = out / (model + ("_facts" if FACTS else "")) / f"{part}.json"
    if f.exists():
        return json.load(open(f))
    notes = json.load(open(NOTES / f"{part}.json"))["notes"]
    facts = ""
    if FACTS:
        p = json.load(open(MERGED / f"{part}.json"))["pred"] or {}
        yn = lambda k: "yes" if p.get(k) else "no"  # noqa: E731
        facts = (f"ESTABLISHED FROM THE CUTS (do not change): edge fillets: {yn('edge_fillets')}; "
                 f"edge chamfers: {yn('edge_chamfers')}. Include fillet/chamfer undo steps only if yes.\n\n")
    t0 = time.time()
    try:
        txt, u = ask_llm(model, P_PLAN.format(bbox=frame(part), notes="\n\n".join(notes), facts=facts))
        plan = VB.parse(txt)
    except Exception as e:                                     # noqa: BLE001  record and move on; resume retries it
        print(json.dumps({"part": part, "error": str(e)[:300]}), flush=True)
        return {"part": part, "error": str(e)[:300]}
    r = {"part": part, "model": model, "seconds": round(time.time() - t0, 1), "usage": u, "plan": plan, "raw": txt,
         "truth": T[part], "score": score(plan, T[part])}
    f.parent.mkdir(parents=True, exist_ok=True)
    json.dump(r, open(f, "w"), indent=1)
    print(json.dumps({"part": part, "seconds": r["seconds"], "score": r["score"]}), flush=True)
    return r


def main():
    out, model = Path(sys.argv[1]), sys.argv[2]
    T = truth()
    parts = sys.argv[3:] or sorted((p for p in T if (NOTES / f"{p}.json").exists()), key=int)
    with ThreadPoolExecutor(1 if model.startswith("qwen") else 4) as ex:
        rows = [r for r in ex.map(lambda p: run(out, model, p, T), parts) if r.get("score")]
    n = len(rows)
    print("SUMMARY", json.dumps({"model": model + ("_facts" if FACTS else ""), "parts": n,
                                 "parsed": sum(r["score"]["parsed"] for r in rows),
                                 **{k: f"{sum(r['score'].get(k, False) for r in rows)}/{n}" for k in KEYS},
                                 "mean_s": round(sum(r["seconds"] for r in rows) / max(n, 1), 1),
                                 "usd": round(sum(r["usage"].get("usd", 0) for r in rows), 3)}), flush=True)


if __name__ == "__main__":
    main()
