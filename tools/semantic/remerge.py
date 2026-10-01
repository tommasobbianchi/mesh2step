"""Re-merge saved per-view notes with the sharper question, and re-score: no image calls, text only.

The first merge asked "any rounded edge" and scored it against fillet OPERATIONS; the models saw the rounded corners a
designer draws IN a sketch (sprocket scallops, pocket corners: 21 of 28 parts) and were marked wrong. The merge now
asks three separate things: rounded corners in the sketch outline, fillets on the extrusion's edges, chamfers on them.

usage: remerge.py <config_dir> [...]        (writes <config_dir>_v2/<part>.json and prints one summary line per dir)"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vlm_bench as VB  # noqa: E402
from truth import truth  # noqa: E402

P_MERGE2 = """Below are notes on the views of ONE mechanical part (6 sides + isometric) and possibly on CUTS through it.
A feature seen in several views is ONE feature: a through hole appears on both opposite faces and counts once.
Keep these three apart, as a designer models them:
- SKETCH ARCS: rounded corners drawn in the outline of the part or of a pocket/slot, seen when looking straight at
  the face the part is extruded from (e.g. rounded rectangle corners, scalloped teeth, a rounded pocket corner);
- EDGE FILLETS: an edge BETWEEN two faces rounded off, e.g. the rim where the top face meets the side walls, seen
  in the side views or in cuts ALONG the extrusion as a rounded corner of the profile;
- EDGE CHAMFERS: such an edge cut off by a small flat bevel.
EVIDENCE RULE: decide EDGE FILLETS and EDGE CHAMFERS ONLY from the CUT notes (when there are cuts): true only if a
cut ALONG the part's thickness (its outline is the part's profile: thin bands, rectangles with steps) shows ROUNDED
(fillet) or BEVELLED (chamfer) corners. Rounded corners in the cut ACROSS the thickness (the one that looks like the
part seen from above) are SKETCH ARCS. The plain-view notes do not vote on edge fillets or chamfers.
Answer ONLY with this JSON object:
{{"part_type": "<a few words>",
 "turned": <true if the part or any feature of it is made by revolving/turning>,
 "holes": <total number of distinct holes, integer>,
 "levels": <number of distinct extruded heights/steps, integer>,
 "sketch_arcs": <true/false>, "edge_fillets": <true/false>, "edge_chamfers": <true/false>,
 "unsure": ["<what you could not tell>"]}}

NOTES:
{notes}"""


def score2(pred, t):
    s = VB.score(pred, t)
    if not pred:
        return s
    s.pop("fillets", None); s.pop("chamfers", None)
    s["sketch_arcs"] = bool(pred.get("sketch_arcs")) == t["sketch_arcs"]
    s["fillets"] = bool(pred.get("edge_fillets")) == t["fillets"]
    s["chamfers"] = bool(pred.get("edge_chamfers")) == t["chamfers"]
    return s


def main():
    T = truth()
    for d in map(Path, sys.argv[1:]):
        out = d.with_name(d.name + "_" + os.environ.get("REMERGE_TAG", "v2")); out.mkdir(exist_ok=True)
        rows = []
        for f in sorted(d.glob("*.json"), key=lambda p: int(p.stem)):
            r = json.load(open(f))
            if not r.get("notes") or r["part"] not in T:
                continue
            if (out / f.name).exists():
                rows.append(json.load(open(out / f.name))); continue
            # REMERGE_MODEL: one text merger for every config, so only the per-view notes differ between them
            txt, u = VB.ask(os.environ.get("REMERGE_MODEL", r["model"]), [], P_MERGE2.format(notes="\n\n".join(r["notes"])), want_json=True)
            pred = VB.parse(txt)
            r2 = {**r, "pred": pred, "score": score2(pred, T[r["part"]]), "truth": T[r["part"]], "raw_merge": txt,
                  "merge2_usage": u}
            json.dump(r2, open(out / f.name, "w"), indent=1); rows.append(r2)
        keys = ["turned", "holes_exact", "holes_pm1", "sketch_arcs", "fillets", "chamfers", "levels_pm1"]
        n = len(rows)
        print(json.dumps({"config": out.name, "parts": n,
                          **{k: f"{sum(r['score'].get(k, False) for r in rows)}/{n}" for k in keys}}), flush=True)


if __name__ == "__main__":
    main()
