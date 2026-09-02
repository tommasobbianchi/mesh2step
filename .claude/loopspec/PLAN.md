# mesh2step v2 — stl2step parity programme

Oracle: `tests/test_parity.py`, 32 cases, **all red at baseline**. Golden fixtures in
`tests/data/reference/` captured from `refs/stl2step/` (v1.1.0 @ 7cf77a2) by
`tools/capture_reference.py`. Regenerating the golden set is a reviewed act, never a fix.

Baseline measured 2026-09-02: P2P `tests/` minus parity = **45 passed**. Lint fingerprint in
`.claude/loopspec/lint-baseline.json`, **64 diagnostics** repo-wide — the gate is the delta, not
zero. Each milestone re-measures its own `src/` baseline: M1 started at 30, M2 starts at **29**.

The M2/M3 boundary was moved twice, both times because a measurement contradicted the split.
First: the M2 F2P subset contains no curved surface, so law-band arc recognition could not be
gated there; M2 became the planar path end to end. Then, during M2: `smoothRejected` is not a
planar counter at all -- `refit_grow.cpp` increments it for each *cylinder* candidate seed that
fails the G1-G4 gates, and that pass runs even on an all-planar mesh. S09 reports 8 of them.
So `S09.trueform`'s last red case moved to M3 with the cylinder stage that produces it, rather
than being faked with a constant. Everything else in S09 -- `facesBeforeUnify` 44 included --
is green under M2.

| M | Deliverable | F2P subset | Turns green |
|---|---|---|---|
| **M1** | RESULT json contract, exit codes 0/2/1, CLI flag parity, component splitting into manifold bodies, sewing/ShapeFix repair path | `-k verbatim` | 16 / 32 |
| **M2** | TrueForm **planar** segmentation and analytic build: region growing, facet-island fallback, closed/valid probe with per-component revert, smooth counters in RESULT | `-k "trueform and (cube or S09)"` | +6 |
| **M3** | TrueForm **curved** recovery: cylinder seeding and the G1-G4 candidate gates (which is where `smoothRejected` comes from), law-band arc recognition (`R = w/(2·sin(θ/2))`), chimera split, self-calibrated law parameters, `Geom_CylindricalSurface` faces | `-k "trueform and (handle-lock or S09)"` | +4 |
| **M4** | Fillet strip recovery; negative control must still decline | `-k "trueform and nonprismatic"` | +3 |
| **M5** | Prismatic 2.5D reconstruction + `--dxf` profile export | `-k "trueform and Body"` | +6 |
| **M6** | Deploy: webapp engine selector, systemd restart, live verification at mesh2step.nativemedica.it | — | — |

Rule for every milestone: the F2P subset goes green **and no earlier subset regresses**.
Cases outside the current subset are known-red and are not evidence of failure.

`/checkpoint` after each milestone. `bd` carries the issue state.
