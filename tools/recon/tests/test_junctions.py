"""junctions.extract: take a B-rep apart into junctions and blends (docs/JUNCTIONS.md, spec specs/junctions.md)."""
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent)); sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import junction_shapes as js  # noqa: E402

HERE = Path(__file__).resolve().parents[1]


def run(builder, tmp_path, **kw):
    import junctions
    return junctions.extract(js.step(getattr(js, builder)(**kw), tmp_path / f"{builder}.step"))


def sigs(recs):
    return Counter(r["sig"] for r in recs)


def test_box_has_twelve_convex_right_angle_edges(tmp_path):
    r = run("box", tmp_path)
    assert sigs(r["junctions"]) == Counter({"plane|plane|line|convex": 12})
    assert all(abs(j["angle"] - 90) < 0.5 and j["tangent"] is False for j in r["junctions"])
    assert r["blends"] == []


def test_inside_corner_is_concave(tmp_path):
    assert sigs(run("l_block", tmp_path)["junctions"])["plane|plane|line|concave"] >= 1


def test_rounded_edges_are_round_cylinder_blends(tmp_path):
    b = run("rounded_box", tmp_path, r=2.0)["blends"]
    assert sigs(b) == Counter({"blend:cylinder|plane+plane|round": 4})
    assert all(abs(x["radius"] - 2.0) < 1e-6 for x in b)


def test_hole_mouths_are_convex_coaxial_circles(tmp_path):
    j = [x for x in run("plate_with_hole", tmp_path, r=3.0)["junctions"] if x["sig"] == "cylinder|plane|circle|convex"]
    assert len(j) == 2 and all(abs(x["radius"] - 3.0) < 1e-6 and x["coaxial"] is True for x in j)


@pytest.mark.parametrize("builder,sig,radius", [
    ("boss_with_base_fillet", "blend:torus|cylinder+plane|fillet", 1.5),
    ("boss_with_top_round", "blend:torus|cylinder+plane|round", 1.0),
])
def test_torus_blends(tmp_path, builder, sig, radius):
    b = [x for x in run(builder, tmp_path)["blends"] if x["sig"] == sig]
    assert len(b) == 1 and abs(b[0]["radius"] - radius) < 1e-6


def test_chamfer_is_a_cone_plane_circle(tmp_path):
    assert sigs(run("chamfered_hole", tmp_path)["junctions"])["cone|plane|circle|convex"] >= 1


def test_records_carry_location(tmp_path):
    r = run("rounded_box", tmp_path)
    for rec in r["junctions"] + r["blends"]:
        assert len(rec["centre"]) == 3
    assert all(j["length"] > 0 for j in r["junctions"])


def test_catalog_counts_signatures_across_parts(tmp_path):
    a = js.step(js.rounded_box(), tmp_path / "a.step"); b = js.step(js.boss_with_base_fillet(), tmp_path / "b.step")
    out = tmp_path / "library.json"
    p = subprocess.run([sys.executable, str(HERE / "junctions.py"), "catalog", str(out), str(a), str(b)],
                       capture_output=True, text=True, timeout=300)
    assert p.returncode == 0, p.stderr[-1500:]
    lib = json.loads(out.read_text())
    assert lib["parts"] == 2
    e = lib["signatures"]["blend:cylinder|plane+plane|round"]
    assert e["count"] == 4 and 1 <= len(e["examples"]) <= 5
    assert {"part", "centre", "radius"} <= set(e["examples"][0])
    assert lib["signatures"]["blend:torus|cylinder+plane|fillet"]["count"] == 1
