"""truth.py hole counting: a hole drawn as a faceted polygon (engine evidence trees use 32-segment loops) is a hole."""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/semantic"))
import truth as T  # noqa: E402


def ngon(n, r=3.0, cx=5.0, cy=-2.0):
    pts = [(cx + r * math.cos(2 * math.pi * k / n), cy + r * math.sin(2 * math.pi * k / n)) for k in range(n)]
    return [{"t": "line", "p": [list(pts[k]), list(pts[(k + 1) % n])]} for k in range(n)]


def test_is_circle_loop():
    assert T.is_circle_loop([{"t": "circle", "c": [0, 0], "r": 2}])
    assert T.is_circle_loop(ngon(32))
    assert T.is_circle_loop(ngon(16))
    assert not T.is_circle_loop(ngon(4))                       # a square is not a hole
    rect = [{"t": "line", "p": [[0, 0], [10, 0]]}, {"t": "line", "p": [[10, 0], [10, 4]]},
            {"t": "line", "p": [[10, 4], [0, 4]]}, {"t": "line", "p": [[0, 4], [0, 0]]}]
    assert not T.is_circle_loop(rect)


def test_faceted_holes_count():
    tree = {"features": [{"op": "pad", "loops": [ngon(4, r=50), ngon(32), ngon(32, cx=-20)]}]}
    assert T.facts(tree)["holes"] == 2


def test_real_trees_with_faceted_holes():
    t = T.truth()
    assert t["17"]["holes"] >= 10 and t["14"]["holes"] >= 10    # engine trees draw these holes as 16/32-gons


def test_hole_through_stacked_levels_counts_once():
    # the same through hole redrawn in two stacked pads is ONE hole (part 14 counted 53 this way)
    tree = {"features": [{"op": "pad", "axis": "Z", "loops": [ngon(4, r=50), ngon(32)]},
                         {"op": "pad", "axis": "Z", "loops": [ngon(4, r=40), ngon(32), ngon(32, cx=-20)]}]}
    assert T.facts(tree)["holes"] == 2
