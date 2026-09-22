"""mesh_junctions.extract: the same junctions and blends, found on a triangle mesh (spec specs/mesh-junctions.md)."""
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent)); sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import junction_shapes as js  # noqa: E402


def run(builder, tmp_path, **kw):
    import mesh_junctions
    return mesh_junctions.extract(js.stl(getattr(js, builder)(**kw), tmp_path / f"{builder}.stl"))


def test_box(tmp_path):
    assert Counter(j["sig"] for j in run("box", tmp_path)["junctions"])["plane|plane|line|convex"] == 12


def test_rounded_edges(tmp_path):
    b = [x for x in run("rounded_box", tmp_path, r=2.0)["blends"] if x["sig"] == "blend:cylinder|plane+plane|round"]
    assert len(b) == 4 and all(abs(x["radius"] - 2.0) / 2.0 < 0.03 for x in b)


def test_hole_mouths(tmp_path):
    j = [x for x in run("plate_with_hole", tmp_path, r=3.0)["junctions"] if x["sig"] == "cylinder|plane|circle|convex"]
    assert len(j) == 2 and all(abs(x["radius"] - 3.0) / 3.0 < 0.03 for x in j)


def test_boss_base_fillet_is_a_torus_fillet(tmp_path):
    b = [x for x in run("boss_with_base_fillet", tmp_path, R=5.0, f=1.5)["blends"]
         if x["sig"] == "blend:torus|cylinder+plane|fillet"]
    assert len(b) == 1 and abs(b[0]["radius"] - 1.5) / 1.5 < 0.05


def test_a_real_corpus_part_in_bounded_time():
    import mesh_junctions
    t0 = time.time()
    r = mesh_junctions.extract(Path("/home/tommaso/corpora/mechparts/15.stl"))
    assert time.time() - t0 < 120
    assert sum(1 for j in r["junctions"] if "cylinder" in j["sig"]) >= 3     # its 3 round faces meet planes
