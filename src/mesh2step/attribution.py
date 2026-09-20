"""IP4 one level up: name what the ENGINE detected and then did not build, and why.

`feature.reconstruct` now names the clause that killed each candidate. The larger loss happens
before it and was invisible. On a real user's hotend assembly (20 656 triangles, live service at
`a087327`, 2026-09-21) the engine detected **36 cylinders, 126 fillets and 1 424 planes**, built
**none of them**, and delivered 4 777 planar faces. Nothing in the log said so.

**The counter that looks like it says so is not trustworthy.** `smoothRevertedComponents` read 1
on that file while `smoothRevertedTrue` read 0 and `usedRefit` was true: the component passed
every gate in `stl2step.cpp` and was adopted, and `refit::buildFaces` simply produced zero
analytic faces from a plan holding 1 586 regions. Measured with the engine's own
`STL2STEP_DIAG_REJECTS=1 --diag-revert-cause`, which reports
`counted-not-reverted usedRefit=true cyls=0 planCyl=36 planPl=1424`.

So the signal this module keys on is **plan versus built**, which is always present and cannot
lie in the same way: the engine says what it detected and what it built, and a detected feature
that does not arrive is the defect, whatever path lost it. The revert counter is reported only as
corroboration, and flagged when it contradicts `smoothRevertedTrue`.

Cause, on that file, from the warnings: 47 x `IntAna <pair> empty/same - keeping mesh polyline`,
then `J6: shell not closed`. The analytic-analytic intersections between adjacent regions come
back `IntAna_Empty`/`IntAna_Same`, the boundary chains stay raw mesh polylines, the analytic shell
cannot close and `buildFaces` falls back to facets for everything. Site:
`refit_build.cpp` `intersectSurfaces`/`pickIntAna` (~1105-1200; `pickIntAna` bails at 725).

**None of this is reachable from Python** and this module does not try: it costs nothing, changes
no decision, and records what died so the next session reads a cause instead of a counter.
"""
from __future__ import annotations

import re

# (needle in the engine's warning text, short cause name). First match wins, in CAUSAL order:
# the failed analytic intersections are why the shell will not close, and the open shell is why
# the build falls back to facets. Reporting the last symptom hides the first cause.
CAUSES = (
    ("IntAna", "analytic-intersection-empty"),
    ("shell not closed", "shell-not-closed"),
    ("B-Rep invalid", "brep-invalid"),
    ("no analytic band survived", "no-band-survived"),
)


def engine_analytic_loss_note(res: dict) -> str | None:
    """One log line when the engine detected curved features and shipped fewer, else None.

    `res` accepts the engine's RESULT payload (camelCase) or the webapp's stats dict
    (snake_case), because this is called from both sides.
    """
    def g(*names, default=0):
        for n in names:
            if res.get(n) is not None:
                return res[n]
        return default

    det_cyl = g("smoothCylinders", "smooth_cylinders")
    det_fil = g("smoothFillets", "smooth_fillets")
    built_cyl = g("smoothBuiltCylinders", "smooth_built_cylinders")
    built_fil = g("smoothBuiltFillets", "smooth_built_fillets")
    lost = (det_cyl - built_cyl) + (det_fil - built_fil)
    if lost <= 0:
        return None

    warns = [str(w) for w in (g("warnings", default=[]) or [])]
    cause, detail = "unnamed", ""
    for needle, name in CAUSES:
        hits = [w for w in warns if needle in w]
        if hits:
            cause = name
            m = re.search(r"freeEdges=(\d+)", hits[0])
            detail = f"(freeEdges={m.group(1)})" if m else f"(x{len(hits)})"
            break

    rev = g("smoothRevertedComponents", "smooth_reverted_components")
    rev_true = g("smoothRevertedTrue", "smooth_reverted_true", default=None)
    note = ""
    if rev and rev_true == 0:
        # The counter increments on a path that is not the true revert. Say so, or the next
        # session debugs a revert that never happened.
        note = f" (revertedComponents={rev} is NOT a revert: revertedTrue=0)"
    elif rev:
        note = f" revertedComponents={rev}"

    return (f"ENGINE_ANALYTIC_LOSS [AC-B2/engine] cause={cause}{detail} "
            f"detected cylinders={det_cyl} fillets={det_fil} -> built cylinders={built_cyl} "
            f"fillets={built_fil} (lost {lost}){note} warnings={len(warns)}")
