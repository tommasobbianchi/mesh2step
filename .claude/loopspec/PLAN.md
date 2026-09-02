# mesh2step v2 — stl2step parity programme

Oracle: `tests/test_parity.py`, 32 cases, **all red at baseline**. Golden fixtures in
`tests/data/reference/` captured from `refs/stl2step/` (v1.1.0 @ 7cf77a2) by
`tools/capture_reference.py`. Regenerating the golden set is a reviewed act, never a fix.

Baseline measured 2026-09-02: P2P `tests/` minus parity = **45 passed**. Lint fingerprint in
`.claude/loopspec/lint-baseline.json`, **64 diagnostics** — the gate is the delta, not zero.

| M | Deliverable | F2P subset | Turns green |
|---|---|---|---|
| **M1** | RESULT json contract, exit codes 0/2/1, CLI flag parity, component splitting into manifold bodies, sewing/ShapeFix repair path | `-k verbatim` | 16 / 32 |
| **M2** | TrueForm segmentation: law-band arc recognition (`R = w/(2·sin(θ/2))`), plane/cylinder region growing, chimera split, self-calibrated law parameters | `-k "trueform and (cube or S09)"` | +4 |
| **M3** | TrueForm analytic face build: `Geom_Plane` / `Geom_CylindricalSurface` faces, analytic edges, revert-to-faceted on failure | `-k "trueform and handle-lock"` | +3 |
| **M4** | Fillet strip recovery; negative control must still decline | `-k "trueform and nonprismatic"` | +3 |
| **M5** | Prismatic 2.5D reconstruction + `--dxf` profile export | `-k "trueform and Body"` | +6 |
| **M6** | Deploy: webapp engine selector, systemd restart, live verification at mesh2step.nativemedica.it | — | — |

Rule for every milestone: the F2P subset goes green **and no earlier subset regresses**.
Cases outside the current subset are known-red and are not evidence of failure.

`/checkpoint` after each milestone. `bd` carries the issue state.
