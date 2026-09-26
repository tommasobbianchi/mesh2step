"""Corpus view of the exact backward move per kept plane: how many undos OCCT accepts, how many it refuses, and
whether a one-plane solid is reached. Raw facts for the engine's next decision, no scoring.

usage: exact_census.py <steps_dir>...
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evidence as E                                   # noqa: E402
import exact as X                                      # noqa: E402
import undo as U                                       # noqa: E402

for d in sys.argv[1:]:
    for p in sorted(Path(d).glob("*.step"), key=lambda p: int(p.stem) if p.stem.isdigit() else 0):
        t0 = time.time()
        try:
            s = E.read(p)
            b = U.base_kind(s)
            tol = 0.5
            row = {"base": [b[0], list(b[1]), round(b[2], 4)]}
            for keep in b[1]:
                ex = X.explained_by(s, (keep,))
                sets = U.unexplained_sets(s, ex)
                acc = sum(U.defeature(s, fs) is not None for fs in sets)
                base, ops = X.reverse_exact(s, keep, tol)
                left = 1 - X.explained_by(base, (keep,)).mean()
                row[f"keep_{'XYZ'[keep]}"] = {"sets": len(sets), "accepted_singly": acc, "undos": len(ops),
                                              "prism_ops": sum(o[1] is not None for o in ops),
                                              "faces_left_unexplained": round(float(left), 3)}
            row["s"] = round(time.time() - t0, 1)
        except Exception as e:                           # noqa: BLE001
            row = {"error": repr(e)[:200]}
        print(p.stem, json.dumps(row), flush=True)
