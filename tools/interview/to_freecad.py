#!/usr/bin/env python3
"""Rebuild history (CadQuery program) -> native FreeCAD PartDesign feature tree (.FCStd), verified.

usage: to_freecad.py <cadquery_program.py> <reference.step> <out.FCStd>
A model translates the program into a PartDesign script (Body -> Sketch -> Pad/Pocket -> Fillet/Chamfer ...),
headless FreeCAD runs it, and the Body's solid must match the reference (valid, symmetric difference < 1 % of its
volume). On failure the error goes back to the same model session; 3 tries. Prints one JSON line.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

CLAUDE = os.path.expanduser("~/.local/bin/claude")
FREECAD = "/snap/bin/freecad.cmd"
TRIES = 3
TOL = 0.01

PROMPT = """Translate this CadQuery program into a FreeCAD 1.1 PartDesign Python script that builds the SAME solid
as an editable feature tree, the way a CAD user would model it by hand.

Rules:
- One PartDesign::Body named "Body". Every step is a PartDesign feature: Sketcher::SketchObject (attached to a
  standard plane or offset with AttachmentOffset) -> PartDesign::Pad / Pocket / Revolution / Groove / Hole, then
  PartDesign::Fillet / Chamfer, PartDesign::LinearPattern / PolarPattern / Mirrored. Never Part:: booleans or
  Part::Feature shapes: the tree must stay editable.
- Keep the program's order (sketch -> extrude -> modify). Give each feature a clear Label ("Ring", "Tail",
  "Bore", "Slot", "Rim chamfer", ...).
- Put the key dimensions in a Spreadsheet named "Params" with aliases and drive the sketch constraints and
  feature lengths from them with setExpression, so the owner edits a number and the model updates.
- Sketches: add geometry AND constraints (coincident, horizontal, vertical, radius/diameter, distances).
- Fillet/Chamfer need edge names: after doc.recompute(), find the edges geometrically on the previous feature's
  Shape (compare edge centre / curve type / length against the program's intent) and pass ("Edge<N>").
- End with: doc.recompute(); doc.saveAs(OUT) where OUT is a variable the harness defines. Use
  `doc = App.newDocument("Part")`. Import FreeCAD as App, Part, Sketcher. No GUI modules.
Reply with ONLY the Python code in one ```python block.

The CadQuery program (the reference solid it built is what yours must match):
```python
{program}
```"""

RUNNER = r'''
import json, sys, traceback
import FreeCAD as App
OUT = {out!r}
res = {{"ok": False}}
try:
    exec(compile(open({script!r}).read(), {script!r}, "exec"), {{"OUT": OUT, "__name__": "gen"}})
    doc = App.openDocument(OUT)
    doc.recompute()
    body = doc.getObject("Body")
    # what the model needs to fix: each feature's state and, for sketches, the solver's complaints
    bad = []
    for o in body.Group:
        st = list(getattr(o, "State", []))
        if "Invalid" in st or "Error" in st or (hasattr(o, "Shape") and o.Shape.isNull() and not o.TypeId.startswith("Sketcher")):
            info = {{"feature": o.Label, "type": o.TypeId, "state": st}}
            if o.TypeId.startswith("Sketcher"):
                for k in ("Conflicts", "Redundancies", "MalformedConstraints", "PartiallyRedundantConstraints"):
                    v = getattr(o, k, None)
                    if v:
                        info[k] = list(v)
                info["solve"] = o.solve()
            bad.append(info)
    sh = body.Shape
    if sh.isNull():
        raise RuntimeError("Body has no shape. Broken features, in tree order: " + json.dumps(bad))
    sh.exportStep({step!r})
    res = {{"ok": True, "valid": sh.isValid(), "volume": sh.Volume, "solids": len(sh.Solids),
            "features": [(o.TypeId.split("::")[-1], o.Label) for o in body.Group], "invalid_features": bad}}
except Exception:
    res["error"] = traceback.format_exc()[-2500:]
open({report!r}, "w").write(json.dumps(res))
'''


def ask(sid, text, cwd):
    cmd = [CLAUDE, "-p", "--tools", "", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
           "--model", "opus", "--output-format", "json"] + (["--resume", sid] if sid else [])
    d = json.loads(subprocess.run(cmd + [text], capture_output=True, text=True, timeout=900, cwd=cwd).stdout)
    m = re.search(r"```python\n(.*?)```", d.get("result") or "", re.S)
    return d.get("session_id"), (m.group(1) if m else d.get("result") or ""), d.get("total_cost_usd") or 0


def compare(a_step, b_step):
    from OCP.STEPControl import STEPControl_Reader
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
    from OCP.GProp import GProp_GProps
    from OCP.BRepGProp import BRepGProp

    def load(p):
        r = STEPControl_Reader(); r.ReadFile(str(p)); r.TransferRoots(); return r.OneShape()

    def vol(s):
        g = GProp_GProps(); BRepGProp.VolumeProperties_s(s, g); return g.Mass()
    a, b = load(a_step), load(b_step)
    va = vol(a)
    sym = vol(BRepAlgoAPI_Cut(a, b).Shape()) + vol(BRepAlgoAPI_Cut(b, a).Shape())
    return va, vol(b), sym / va


def main():
    prog, ref, out = Path(sys.argv[1]), Path(sys.argv[2]).resolve(), Path(sys.argv[3]).resolve()
    wd = out.parent
    sid, cost, last = None, 0.0, None
    text = PROMPT.format(program=prog.read_text())
    for attempt in range(1, TRIES + 1):
        sid, code, c = ask(sid, text, wd)
        cost = max(cost, c)
        script, report, step = wd / f"fc_try{attempt}.py", wd / f"fc_try{attempt}.json", wd / f"fc_try{attempt}.step"
        script.write_text(code)
        runner = wd / f"fc_run{attempt}.py"
        runner.write_text(RUNNER.format(out=str(out), script=str(script), step=str(step), report=str(report)))
        subprocess.run([FREECAD, str(runner)], capture_output=True, text=True, timeout=600)
        r = json.loads(report.read_text()) if report.exists() else {"ok": False, "error": "FreeCAD wrote no report"}
        if r.get("ok") and r.get("valid") and r.get("solids") == 1 and not r.get("invalid_features"):
            va, vb, rel = compare(ref, step)
            r.update(ref_volume=round(va, 3), fc_volume=round(vb, 3), symdiff=round(rel, 5))
            if rel < TOL:
                print(json.dumps({"ok": True, "attempts": attempt, "cost_usd": round(cost, 3), **r}))
                return 0
            text = (f"The FreeCAD body differs from the reference solid: symmetric difference {rel:.2%} of its volume "
                    f"(reference {va:.2f} mm3, yours {vb:.2f}). Features: {r['features']}. Fix it; same output rules.")
        else:
            text = ("Running your script failed or the Body is not one valid solid: "
                    f"{json.dumps({k: r.get(k) for k in ('error', 'valid', 'solids', 'invalid_features')})[:2800]}"
                    " Fix it; same output rules.")
        last = r
    print(json.dumps({"ok": False, "attempts": TRIES, "cost_usd": round(cost, 3), "last": last}))
    return 1


if __name__ == "__main__":
    sys.exit(main())
