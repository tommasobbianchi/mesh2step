"""VLM bake-off for semantic reverse engineering (docs/SEMANTIC-RE.md, milestone M1): which vision model, at which tile
grid, describes a part correctly, and at what cost. The winner is the cheapest configuration that scores within a
small margin of the best, over the whole set, never on one part.

Protocol, the same for every model: per view (7 views) one call with the view's overview + its g x g tiles, answered in
words; then one text-only call to the same model merging the 7 notes into a JSON inventory. Scored against truth.py (the
owner's 5/5 feature trees): turned, holes (exact and within 1), fillets, chamfers, levels (within 1).

usage: vlm_bench.py <out_dir> <model> <grid> [part ...]
  model: deepseek | qwen30b | qwen8b        grid: 1 (overview only) | 2 | 4"""
import base64
import json
import os
import re
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, os.path.expanduser("~/.claude/skills/deepseek-vision/scripts"))
import tiles as TL  # noqa: E402
from truth import truth  # noqa: E402

MESHES = Path.home() / "corpora" / "mechparts"
QWEN = {"qwen30b": "qwen3-vl:30b-a3b-instruct-q4_K_M", "qwen8b": "qwen3-vl:8b-instruct-q4_K_M"}

P_VIEW = """You are looking at ONE view of a mechanical part (a CAD model rendered orthographically, grey shading).
The first image is the whole view. {tiles_note}
Describe what this view shows, as a designer would, in plain words:
- the outline shape of the part in this view;
- holes (through or blind), how many and how they are arranged;
- pockets, slots, cut-outs;
- bosses, ribs, steps or distinct flat levels (heights);
- fillets (rounded edges) and chamfers (bevelled, flat-cut edges), and where;
- anything round that looks turned on a lathe (shafts, discs, round grooves).
Give counts, never measurements. If something is unclear, say so."""

P_TILES = ("The next {n} images are tiles that enlarge the same view in a {g}x{g} grid, labelled r<row>c<col>, "
           "left to right and top to bottom, overlapping slightly. Use them to see small features; a feature cut by a "
           "tile edge appears in two neighbouring tiles and is still ONE feature.")

P_MERGE = """Below are notes on the 7 views (+X, -X, +Y, -Y, +Z top, -Z bottom, isometric) of ONE mechanical part.
A feature seen in several views is ONE feature: a through hole appears on both opposite faces and counts once.
Answer ONLY with this JSON object, nothing else:
{{"part_type": "<what the part is, a few words>",
 "turned": <true if the part or any of its features is made by revolving/turning: shaft, disc, bushing, round boss or groove>,
 "holes": <total number of distinct holes, integer>,
 "levels": <number of distinct extruded heights/steps of the body, integer>,
 "fillets": <true if any edge is rounded>,
 "chamfers": <true if any edge is bevelled flat>,
 "features": ["<short list of the features>"],
 "unsure": ["<what you could not tell>"]}}

NOTES:
{notes}"""


def _b64(p):
    return base64.b64encode(open(p, "rb").read()).decode()


def ask_deepseek(images, prompt, want_json=False):
    import ask as DS
    content = [{"type": "text", "text": prompt}]
    for lab, p in images:
        content += [{"type": "text", "text": f"[{lab}]"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64," + _b64(p)}}]
    body = {"model": DS.MODEL, "messages": [{"role": "user", "content": content if images else prompt}],
            "temperature": 0.0, "max_tokens": 24000, "reasoning_effort": "low"}
    req = urllib.request.Request(f"{DS.BASE}/v1/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {DS._key()}"})
    with urllib.request.urlopen(req, timeout=600) as r:
        j = json.loads(r.read())
    u = j.get("usage", {})
    return j["choices"][0]["message"].get("content") or "", {"in": u.get("prompt_tokens", 0), "out": u.get("completion_tokens", 0)}


def ask_qwen(model, images, prompt, want_json=False):
    msg = {"role": "user", "content": prompt}
    if images:
        msg["content"] = prompt + "\n" + "\n".join(f"Image {i + 1}: [{lab}]" for i, (lab, _p) in enumerate(images))
        msg["images"] = [_b64(p) for _lab, p in images]
    body = {"model": QWEN[model], "messages": [msg], "stream": False,
            "options": {"temperature": 0, "num_ctx": 32768}}
    if want_json:
        body["format"] = "json"
    req = urllib.request.Request("http://127.0.0.1:11434/api/chat", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=1800) as r:
        j = json.loads(r.read())
    return j["message"]["content"], {"in": j.get("prompt_eval_count", 0), "out": j.get("eval_count", 0)}


def ask(model, images, prompt, want_json=False):
    return ask_deepseek(images, prompt, want_json) if model == "deepseek" else ask_qwen(model, images, prompt, want_json)


def parse(text):
    m = re.search(r"\{.*\}", text, re.S)
    try:
        return json.loads(m.group(0)) if m else None
    except ValueError:
        return None


def score(pred, t):
    if not pred:
        return {"parsed": False}
    def num(k):
        try:
            return int(pred.get(k))
        except (TypeError, ValueError):
            return None
    h, lv = num("holes"), num("levels")
    return {"parsed": True, "turned": bool(pred.get("turned")) == t["turned"],
            "holes_exact": h == t["holes"], "holes_pm1": h is not None and abs(h - t["holes"]) <= 1,
            "fillets": bool(pred.get("fillets")) == t["fillets"], "chamfers": bool(pred.get("chamfers")) == t["chamfers"],
            "levels_pm1": lv is not None and abs(lv - t["levels"]) <= 1}


def run_part(part, model, grid, out, t):
    views = TL.all_views(MESHES / f"{part}.stl", out / "renders" / part, grid)
    t0 = time.time(); usage = {"in": 0, "out": 0, "images": 0, "calls": 0}; notes = []
    for v in TL.VIEWS:
        imgs = views[v]
        prompt = P_VIEW.format(tiles_note=P_TILES.format(n=len(imgs) - 1, g=grid) if grid > 1 else "")
        txt, u = ask(model, imgs, prompt)
        notes.append(f"[{v}]\n{txt.strip()}")
        usage["in"] += u["in"]; usage["out"] += u["out"]; usage["images"] += len(imgs); usage["calls"] += 1
    txt, u = ask(model, [], P_MERGE.format(notes="\n\n".join(notes)), want_json=True)
    usage["in"] += u["in"]; usage["out"] += u["out"]; usage["calls"] += 1
    pred = parse(txt)
    row = {"part": part, "model": model, "grid": grid, "seconds": round(time.time() - t0, 1), "usage": usage,
           "truth": t, "pred": pred, "score": score(pred, t)}
    (out / f"{model}_g{grid}").mkdir(parents=True, exist_ok=True)
    json.dump({**row, "notes": notes, "raw_merge": txt}, open(out / f"{model}_g{grid}" / f"{part}.json", "w"), indent=1)
    return row


def main():
    out, model, grid = Path(sys.argv[1]), sys.argv[2], int(sys.argv[3])
    T = truth()
    parts = sys.argv[4:] or list(T)
    # renders first, several parts at once (CPU); then the model calls (DeepSeek in parallel, local Qwen one at a time)
    with ThreadPoolExecutor(6) as ex:
        list(ex.map(lambda p: TL.all_views(MESHES / f"{p}.stl", out / "renders" / p, grid), parts))
    workers = 4 if model == "deepseek" else 1
    rows = []
    with ThreadPoolExecutor(workers) as ex, open(out / "bench.jsonl", "a") as fh:
        for row in ex.map(lambda p: run_part(p, model, grid, out, T[p]), parts):
            fh.write(json.dumps(row) + "\n"); fh.flush(); rows.append(row)
            print(json.dumps({k: row[k] for k in ("part", "seconds", "score")}), flush=True)
    keys = ["turned", "holes_exact", "holes_pm1", "fillets", "chamfers", "levels_pm1"]
    ok = [r for r in rows if r["score"].get("parsed")]
    summ = {"model": model, "grid": grid, "parts": len(rows), "parsed": len(ok),
            **{k: round(sum(r["score"][k] for r in ok) / max(len(rows), 1), 3) for k in keys},
            "mean_s": round(sum(r["seconds"] for r in rows) / max(len(rows), 1), 1),
            "images_per_part": round(sum(r["usage"]["images"] for r in rows) / max(len(rows), 1), 1),
            "tokens_in_per_part": round(sum(r["usage"]["in"] for r in rows) / max(len(rows), 1)),
            "tokens_out_per_part": round(sum(r["usage"]["out"] for r in rows) / max(len(rows), 1))}
    print("SUMMARY " + json.dumps(summ), flush=True)
    with open(out / "summary.jsonl", "a") as fh:
        fh.write(json.dumps(summ) + "\n")


if __name__ == "__main__":
    main()
