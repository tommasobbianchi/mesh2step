"""Corpus census of the exact backward move: per part, the base the production solid needs, the undo sets the base
cannot explain, and whether undoing them leaves an exact 1-2 plane base. The corpus-level measure of the
approach (docs/ENGINE.md section 6), not a per-part check.

usage: undo_census.py <steps_dir>...
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evidence as E                                   # noqa: E402
import undo as U                                       # noqa: E402

rows = {}
for d in sys.argv[1:]:
    for p in sorted(Path(d).glob("*.step"), key=lambda p: int(p.stem) if p.stem.isdigit() else 0):
        if p.stem in rows:
            continue
        t0 = time.time()
        try:
            s = E.read(p)
            b = U.base_kind(s)
            sets = U.unexplained_sets(s, b[3])
            t = U.defeature(s, [f for x in sets for f in x]) if sets else s
            accepted = None
            if t is None:
                accepted = sum(U.defeature(s, x) is not None for x in sets)
            b2 = U.base_kind(t) if t is not None else None
            r = {"faces": len(U.faces(s)), "planes": b[0], "axes": list(b[1]), "unexplained": round(b[2], 4),
                 "undo_sets": len(sets), "all_at_once": t is not None, "sets_accepted_singly": accepted,
                 "after_planes": b2[0] if b2 else None, "after_unexplained": round(b2[2], 4) if b2 else None,
                 "s": round(time.time() - t0, 1)}
        except Exception as e:                           # noqa: BLE001
            r = {"error": repr(e)[:200]}
        rows[p.stem] = r
        print(p.stem, json.dumps(r), flush=True)
ok = [r for r in rows.values() if "error" not in r]
exact = [r for r in ok if r["after_unexplained"] is not None and r["after_unexplained"] < 0.005]
print(json.dumps({"parts": len(ok), "exact_base_after_undo (<0.5% unexplained)": len(exact),
                  "one_plane": sum(r["after_planes"] == 1 for r in exact),
                  "two_planes": sum(r["after_planes"] == 2 for r in exact),
                  "defeature_refused": sum(not r["all_at_once"] for r in ok)}))
