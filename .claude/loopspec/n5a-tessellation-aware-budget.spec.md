# n5a — tessellation-aware revert budget

> **REFUTED 2026-09-06. Implemented, measured, and it makes things worse. Do not ship.**
> The corrected cause census puts the budget at 2 of 19 reverts (buildFaces-empty is 15).
> On the only two models it can reach it fails its own gates: `L04_soap_bar` emits a
> **negative volume** (−2512.010 mm3 against a mesh of 4102.934) once the allowance
> suppresses the revert, and `L10_tool_holder_recon` — which has ZERO cylinders in ground
> truth — gains a false rebuild. The revert budget is load-bearing: it is what stops a
> broken rebuild reaching the output. Code kept on branch `n5a-tess-budget` behind
> `STL2STEP_N5A_OFF` as the record of a closed route.

**Status: REFUTED (was: PROPOSAL, smallest change, largest measured gain).**
Splitting n5 into n5a/n5b/n5c is deliberate: a mixed fix cannot be attributed.

## 0. THE MEASUREMENT THAT JUSTIFIES IT (P7, confirmed)

`stl2step.cpp:1063`, `budget = max(1e-4*refVol, 3*dVolPredAbs)`. The volume change a
**correct** rebuild must make, `SUM over bands of V_band*(1 - (n/2pi)*sin(2pi/n))`:

| model | budget | correct rebuild's dV | over | reverted |
|---|---|---|---|---|
| `L06_adapter_plate` | 2.856 | **79.382** | **27.8x** | 1 |
| `L04_cyl_bottom_chamf` | 0.758 | **16.806** | **22.2x** | 1 |

Per-band fractions: n=59 -> 0.189 %, n=52 -> 0.243 %, n=26 -> 0.971 %, n=24 -> 1.15 %.
The `3*dVolPredAbs` term is excluded by observation: the reverts fired, so it did not
cover the change either.

**The guard reads "the volume moved a lot" as "the rebuild is wrong", when for a coarse
tessellation a large move is exactly what a correct rebuild produces.**

## 1. TARGET GOAL

Make the budget tessellation-aware: derive the EXPECTED volume change from the model's own
(d, alpha) fingerprint — the same one `intent.audit_engine_cylinders` already fits — and
revert only on a change the fingerprint does NOT explain.

For each rebuilt band of radius R, height h and n sides, the explained change is
`V_band * (1 - (n/2pi)*sin(2pi/n))`. Sum over bands, allow a margin, and compare against
the actual change. One fingerprint, both decisions: the same numbers that flag a designed
prism (n4) explain a legitimate volume move here.

- **Scope:** the fork ONLY (`refs/` is read-only reference truth; separate checkout at
  **7cf77a2**, own build dir, `MESH2STEP_NATIVE` pointed at it only for the A/B).
- **Non-goal:** touching IntAna (n5b) or the seamed/mixed boundary (n5c). If this change
  alone does not move the corpus, that is a result, not a reason to widen it.

## 2. GATES (all required)

- [ ] default path byte-identical to the frozen engine on all 57 models when the new
      budget is disabled;
- [ ] `L06_adapter_plate` and `L04_cyl_bottom_chamf` no longer revert, and their volumes
      move toward the B-Rep truth (baseline errors 36.94 and 3.41 mm3 respectively);
- [ ] the 8-gon archetype STILL does not become a silent cylinder (n4's job, must not regress);
- [ ] corpus recall >= baseline on every model, strictly better on >= 1;
- [ ] zero false rebuilds (volume moved away from B-Rep truth);
- [ ] the designed-polygon negatives, once they exist, are not rebuilt.

## 3. ORDERING

P10 (revert cause census) says how much of the corpus this reaches. Prediction:
budget-only is the majority. Run n5a first regardless — it is the smallest diff and the
only one whose gain is already quantified.
