"""Closed loop: a known tree -> its solid -> a mesh of it -> propose() must find the same construction.
run: python3 -m pytest -q tools/tree/test_tree.py   (about a minute)"""
import sys
import tempfile
from pathlib import Path

import numpy as np
import trimesh

sys.path.insert(0, str(Path(__file__).resolve().parent))
import propose as PR                                   # noqa: E402
import tree as T                                       # noqa: E402

RECT = [[0, 0], [40, 0], [40, 20], [0, 20]]
PLATE = {"units": "mm", "features": [
    {"id": "F1", "op": "pad", "label": "Plate", "axis": "Z", "at": 0.0, "length": 6.0,
     "loops": [[{"t": "line", "p": [RECT[i], RECT[(i + 1) % 4]]} for i in range(4)]]},
    {"id": "F2", "op": "pocket", "label": "Hole", "axis": "Z", "at": 0.0, "length": "through",
     "loops": [[{"t": "circle", "c": [12, 10], "r": 4.0}]]},
    {"id": "F3", "op": "pocket", "label": "Cross hole", "axis": "X", "at": 30.0, "length": 10.5,
     "loops": [[{"t": "circle", "c": [10, 3], "r": 1.5}]]},                  # u = Y, v = Z around X
    {"id": "F4", "op": "chamfer", "label": "Rims", "size": 1.0, "on": "F1", "cap": "both", "loops": "outer"}]}


def test_compile_is_exact():
    s, notes = T.compile_tree(PLATE, 0.05)
    assert not notes
    v = 40 * 20 * 6 - np.pi * 16 * 6 - np.pi * 1.5 ** 2 * 10
    assert abs(T.volume(s) - v) / v < 0.03                  # the rim chamfers take the rest


def test_propose_recovers_the_tree():
    s, _ = T.compile_tree(PLATE, 0.05)
    V, F = T.tessellate(s, 0.01)
    with tempfile.TemporaryDirectory() as d:
        stl = Path(d) / "plate.stl"
        trimesh.Trimesh(V, F).export(stl)
        tree, m, tol = PR.propose(str(stl))
    ops = [(f["op"], f.get("axis")) for f in tree["features"]]
    assert ops[0] == ("pad", "Z")
    assert ("pocket", "Z") in ops and ("pocket", "X") in ops         # the through hole and the cross hole
    ch = [f for f in tree["features"] if f["op"] == "chamfer"]
    assert ch and abs(ch[0]["size"] - 1.0) < 0.15
    s2, _ = T.compile_tree(tree, tol)
    assert T.deviation(m, s2, tol)["explained"] > 0.98


def test_fcstd_script_generates_for_every_op():
    """The FreeCAD script is generated for pads, pockets, tapered and edge modifiers (no FreeCAD needed): a
    deleted local once broke every export with an edge round and no check noticed."""
    import fcstd
    t = {"units": "mm", "features": PLATE["features"][:3] + [
        {"id": "F4", "op": "round", "label": "Rims", "size": 1.0, "on": "F1", "cap": "both", "loops": "outer"},
        {"id": "F5", "op": "chamfer", "label": "Hole mouth", "size": 0.5, "on": "F1", "cap": "top", "loops": "inner"}]}
    src = fcstd.script(t, "/tmp/x.FCStd", "/tmp/x.json", 0.05)
    compile(src, "gen", "exec")
    assert "modifier('Fillet'" in src and "modifier('Chamfer'" in src
    assert "taper=-45.0" in fcstd.script(PLATE, "/tmp/x.FCStd", "/tmp/x.json", 0.05)


def test_fix_patch_keeps_summarised_sketches():
    import fix
    big = dict(PLATE["features"][0], loops=[[{"t": "line", "p": [[i, 0], [i + 1, 0]]} for i in range(200)]])
    t = {"units": "mm", "features": [big] + PLATE["features"][1:]}
    c = fix.compact(t)
    assert isinstance(c["features"][0]["loops"], str)                          # summarised for the model
    n = fix.apply_patch(t, {"replace": [dict(c["features"][0], label="Base")], "remove": ["F3"],
                            "add": [{"op": "pocket", "label": "Slot", "axis": "Z", "at": 0, "length": "through",
                                     "loops": [[{"t": "circle", "c": [30, 10], "r": 2}]]}]})
    assert n["features"][0]["label"] == "Base" and n["features"][0]["loops"] == big["loops"]
    assert [f["id"] for f in n["features"]] == ["F1", "F2", "F5", "F4"]        # added before the chamfer
    assert fix.first_json('ok {"add": []} and {braces} after', "add") == {"add": []}


def test_multibody_split_and_compile():
    """A print-in-place part is several closed bodies: each gets its own tree, compiled to its own solid."""
    import analyse
    a = trimesh.creation.box([10, 10, 10])
    b = trimesh.creation.box([4, 4, 4]); b.apply_translation([20, 0, 0])          # 13 mm apart
    dust = trimesh.creation.box([0.05, 0.05, 0.05]); dust.apply_translation([40, 0, 0])
    bs = analyse.bodies(trimesh.util.concatenate([a, b, dust]))
    assert [round(abs(m.volume)) for m, _ in bs] == [1000, 64] and all(full for _, full in bs)
    t = {"units": "mm", "features": [dict(f, body="B1") for f in PLATE["features"][:2]] +
         [dict(f, id="G" + f["id"], body="B2", at=20.0) for f in PLATE["features"][:1]]}
    s, notes = T.compile_tree(t, 0.05)
    from OCP.TopAbs import TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer
    ex, n = TopExp_Explorer(s, TopAbs_SOLID), 0
    while ex.More():
        n += 1; ex.Next()
    assert n == 2 and not notes
    assert abs(T.volume(s) - (2 * 40 * 20 * 6 - np.pi * 16 * 6)) < 1
