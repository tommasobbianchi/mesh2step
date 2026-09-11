# n8 — the cascade destroys the faces it built

Opened 2026-09-07. bd: projects-6p0 (was "UNEXPLAINED: what in the n5e curve rule produced +178").
ANSWERED by W10, binary f1ce95c14767, branch n8-p70-facebuild (contains c3c3a56, excludes
720320a), parity SAME on L06 and NEG_SC-59 with the diagnostic off.

## The measurement

SpeedTestStructure_normal, CYLINDER regions only, per buildFaces pass on the current line:

| pass | sum nCollapsed (of 1247 chains) | % | analytic cylinder faces (builtAs=Single) |
|---|---|---|---|
| 0 | 567 | 45.5 | **165** |
| 1 | 458 | 36.7 | 165 |
| 2 | 458 | 36.7 | 165 |
| 3 | 278 | 22.3 | 128 |
| 4 | 263 | 21.1 | 125 |
| 5 | **0** | **0.0** | **0** (183 Exploded) |

Segmentation is IDENTICAL between the two binaries: same root, same 725 regions, same 183
cylinder ids, onlyMine=0, onlyN5e=0. So the curve rule does not change what is recognised.

Final-pass join, all 183 cylinder regions, two distinct rows:

| count | mine emitted/reject/builtAs | n5e emitted/reject |
|---|---|---|
| 178 | 1(facets) / FaceBuildFailed / ExplodedToFacets | 1 / None |
| 5 | 1(facets) / FaceBuildFailed / ExplodedToFacets | 0 / FaceBuildFailed |

The 5 that fail on BOTH are ids 8-12 (nTris 32/32/32/28/28, R=10.000, nChains=4) -- a hard case
independent of this mechanism.

## The claim, and it inverts the chapter

**The engine BUILDS 165 analytic cylinder faces at pass 0 and then destroys them.** Every
cascade retry uncollapses more chains (567 -> 458 -> 278 -> 263 -> 0); with zero collapsed chains
no analytic cylinder face can exist. `FaceBuildFailed 183` in the final histogram is a misleading
name: the faces did not fail to build, they were built and then dismantled.

**So the n5e curve rule never "enabled" cylinder construction. It PREVENTED THE ATTRITION** by
keeping some chains as polylines from the start, so the retry loop never escalates to total
uncollapse. That is why it gained 178 cylinders, and its 40-cylinder cost on the fine meshes was
the price of applying that prevention indiscriminately.

## RISK this creates for n5j (my own change)

`n5j-j6-progress` lets the J6 heal continue WHILE IT MAKES PROGRESS instead of capping at one
pass. The heal works by UNCOLLAPSING chains. More passes therefore means more uncollapsing, and
this measurement shows uncollapsing is what destroys the cylinders. **n5j may be accelerating the
attrition it was meant to help.** It is committed, gated and unpromoted; before it goes anywhere
near a promotion, measure the pass trajectory with and without it on the same binary.

## Reachability control (satisfied)

builtAs=Single was observed on my branch on all three NEG models (12/16/12), on
SpeedTestStructure_coarse (75), and on SpeedTestStructure_normal itself in passes 0-4
(165,165,165,128,125). So `Exploded x183` at the final pass is a measurement, not a dead branch.

## Cross-model histograms (cylinder regions)

| model | mine | n5e |
|---|---|---|
| SpeedTestStructure_normal | FaceBuildFailed 183 | None 178, FaceBuildFailed 5 |
| SpeedTestStructure_coarse | **None 75**, FaceBuildFailed 76 | FaceBuildFailed 151 |
| NEG_SC-59_fine | None 12, FaceBuildFailed 1 | FaceBuildFailed 13 |
| NEG_SOT-143_fine | None 16, FaceBuildFailed 1 | None 17 |
| NEG_TSOT-23_fine | None 12, FaceBuildFailed 1 | FaceBuildFailed 13 |

On COARSE the current line is BETTER than the n5e stack (75 analytic cylinders vs 0).

## P70 — pending. Keep the best pass, not the last

Claim: the engine already produces the wanted result at pass 0 and discards it. If the cascade
kept the BEST pass by some measure (most analytic faces on a shell that is closed and valid)
instead of the last, SpeedTestStructure_normal would ship of order 165 cylinders with no new
geometry and no new threshold.

- **P70a** at least one pass on SpeedTestStructure_normal produces a shell that is BOTH closed
  and BRepCheck-valid AND carries analytic cylinder faces. Predicted: pass 0, 1 or 2 (165 faces).
- **P70b** the same is true on the models that currently revert for other causes (L08_T_bracket,
  clamp_half_a), i.e. the attrition is general, not specific to this model.
- **P70c** keeping the best pass costs no sentinel: NEG_SC-59 12, NEG_SOT-143 16, NEG_TSOT-23 12,
  L06 14, L01 1, gripper_gear 11 unchanged, because those models converge in 1-2 passes and their
  best pass IS their last.

Falsified if no pass is simultaneously closed, valid and cylinder-bearing -- then the attrition is
not incidental, the early passes are genuinely unusable, and the retry is doing necessary work.

## Instrument caveats carried forward (from W10, not to be lost)

- `emitted` on the current line counts FACETS: `builtRid.push_back(exp ? rid : -1)` at
  refit_build.cpp:4603 means an ExplodedToFacets region scores emitted=1. **`builtAs` is the
  honest discriminator** for "an analytic face was built".
- The n5e binary's DIAG_PLAN has no chain fields, so nChains/nCollapsed are current-line only.
- buildFaces runs 1-6 times per component; any per-region table must say which pass it reports.
