#!/usr/bin/env python3
"""What did the feature pass throw away? Every candidate, gated AND scored for representation.

`feature.reconstruct` reports a candidate's gate clauses (IP4). It cannot report what the
candidate would have DELIVERED, because the corpus instrument is bench-only (guideline 2.3:
`patch_representation` costs seconds to minutes per part and never runs in the conversion path).
This probe closes that gap off-line: it runs the same candidate list, applies the same gate, and
then scores each written STEP with the same instrument the baseline used.

That is the only way to tell an immune rejection that SAVED the user from one that COST him:
both read `REJECT support [AC-B4]` in the log, and only this distinguishes 15-real-plus-65-invented
from a build the mesh backs everywhere and the radius test cannot see.

`--refine` additionally re-runs the density-knob builders at their higher setting, which answers
whether "spend longer on one candidate" is worth pointing at a build that already qualifies.

usage: candidate_probe.py <part> [<part>...] [--refine] [--only stepped extrude-z]
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from mesh2step.backing import backed_fraction  # noqa: E402
from mesh2step.feature import (_candidates, _mesh, _read, _refine_argv,  # noqa: E402
                               failures, mesh_cylinder_radii, measure, support)
from patch_representation import represent, step_entity_census  # noqa: E402


def probe(part: str, stl: Path, wd: Path, only: list[str], refine: bool, timeout: float) -> None:
    tri = _mesh(stl)
    radii = mesh_cylinder_radii(tri)
    print(f"\n== part {part}: {len(tri)} triangles, mesh shows {len(radii)} cylinder patches",
          flush=True)
    jobs = [(lab, argv, env, out) for lab, argv, env, out in _candidates(stl, wd)
            if not only or lab in only]
    if refine:
        for lab, argv, env, out in list(jobs):
            r = wd / f"{lab}.refine.step"
            ra = _refine_argv(lab, argv, r)
            if ra:
                jobs.append((f"{lab}+refine", ra, env, r))
    for lab, argv, env, out in jobs:
        t0 = time.time()
        try:
            subprocess.run([str(a) for a in argv], capture_output=True, timeout=timeout,
                           env=dict(AXIS=env.get("AXIS", ""), PATH="/usr/bin:/bin"), cwd=str(wd))
        except subprocess.TimeoutExpired:
            print(f"   {lab:<18} TIMEOUT {timeout:.0f}s", flush=True)
            continue
        secs = time.time() - t0
        if not Path(out).exists():
            print(f"   {lab:<18} {secs:6.0f}s  no output", flush=True)
            continue
        try:
            m = measure(Path(out), tri)
            sup = support(m["radii"], radii) if m and m["cylinders"] else None
            f = failures(m, 0, sup)
            r = represent(stl, Path(out))
            e = step_entity_census(Path(out).read_bytes())
            bf, bn, bt = backed_fraction(_read(Path(out)), tri)
        except Exception as exc:  # noqa: BLE001
            print(f"   {lab:<18} {secs:6.0f}s  measure/score failed: {exc}", flush=True)
            continue
        print(f"   {lab:<18} {secs:6.0f}s  {('ACCEPT' if not f else 'REJECT ' + f[0]):<15} "
              f"cyl={m['cylinders']:4} sup={(-1 if sup is None else sup):5.2f} "
              f"backed={bn:4}/{bt:<4}={bf:4.2f} "
              f"dv={m['dv_pct']:+8.3f}% p95={m['dist_p95']:7.4f}/{0.005*m['diag']:.4f} "
              f"solids={m['solids']} valid={int(m['valid'])} | curved={r['curved']:3}/"
              f"{r['patches']:3} plane={r['plane']:3} far={r['far']:3} "
              f"cyl_ents={e['CYLINDRICAL_SURFACE']:4}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("parts", nargs="+")
    ap.add_argument("--dir", default="~/corpora/mechparts")
    ap.add_argument("--workdir", default="/tmp/candidate_probe")
    ap.add_argument("--only", nargs="*", default=[])
    ap.add_argument("--refine", action="store_true")
    ap.add_argument("--timeout", type=float, default=2400.0)
    a = ap.parse_args()
    for part in a.parts:
        wd = Path(a.workdir).expanduser() / part
        wd.mkdir(parents=True, exist_ok=True)
        probe(part, Path(a.dir).expanduser() / f"{part}.stl", wd, a.only, a.refine, a.timeout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
