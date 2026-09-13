# RESUME — state at 2026-09-13 08:55, for `claude --continue`

Client (behemoth) was restarted; nativedev, the jobs and this transcript were not affected.

## Live service

v1.8.0-fc0d7911ba1b, `active`. Drop-in: ~/.config/systemd/user/mesh2step.service.d/native.conf
Rollback chain: `native.conf.v180-rollback` (v1.6.0) · `.v170-rollback` · `.v160-rollback`
Engine dir: ~/.local/share/mesh2step-native-v1.8.0-fc0d7911ba1b/{stl2step,lib,run.sh}

## Agents that were running — CHECK THESE FIRST

    ~/.claude/scripts/job status kimi3      # Kimi: keep-open exit + t4 skip for open shells
    ~/.claude/scripts/job status ocds3      # DeepSeek: part-11 exit path + UV pcurve

Outputs (all on nativedev, /tmp survives since nativedev did not reboot):
    SCR=/tmp/claude-1000/-home-tommaso-projects-mesh2step/55ed36d6-4f09-4e83-a602-2227174fbd8a/scratchpad
    $SCR/n19/kimi3.out                 $SCR/wt-kimi/FINDINGS-CLOSURE.md   (Kimi, incremental)
    $SCR/n19/ocds3.out                 $SCR/wt-ds/                        (DeepSeek)
    $SCR/wt-p84/                       my own worktree (n19..n28)

Worktrees are snapshotted as patches in .claude/loopspec/patches/ in case /tmp is ever lost:
    n19-n28-engine-arms.patch     my tree
    wip-kimi-closure.patch        Kimi, in flight at snapshot time
    wip-deepseek-closure.patch    DeepSeek, in flight at snapshot time

## THE GOAL (unchanged)

Every cylinder, torus and fillet present in the mesh must appear in the STEP, on the
user's own parts in ~/corpora/mechparts (40 files). Runtime is NOT a concern -- the user
said so explicitly. Corpus gate that must not regress: cadbench normal **73.67**,
fine **50.13** (scripts/radius_audit.py + scripts/cadscore.py).

## Where the user's parts stand

| part | tris | curved% | cylinders shipped |
|---|---|---|---|
| 22 | 23,364 | 77 | **3** (was 0 -- the v1.8.0 win) |
| 15 | 1,784 | 7.8 | 1 |
| 8 | 1,832 | 4.8 | 2 |
| 26 / 2 / 34 / 13 | 2-3k | 42-62 | 1 / 2 / 3 / 2 |
| **9** | 46,104 | 88 | **0** — 98 cylinder regions recognised, 0 built |
| **11** | 46,674 | 98 | **0** — 56 recognised, 0 built |
| 29 / 31 / 3 / 5 | 3-6k | 34-57 | 0 |
| 37 others | | | **never measured** |

No part ships a TORUS. 3 parts exceed the 120k-triangle app limit (12, 23, 39).

## Next actions, in order

1. Read both agents' output. Kimi's keep-open approach is the most promising line: a
   labelled keep-open exit that preserves built analytic faces, with t4 volume
   verification skipped FOR THAT EXIT ONLY (open-shell volume is meaningless -- a
   167-free-edge shell integrates 15,139 vs a true 97,838 mm3) and t3 validity kept strict.
2. Relay to DeepSeek: `line=6038` is NOISE. Kimi established it is inside the `addId`
   lambda, so it is not part 11's real return-false. I had passed it on as if it were.
3. Any candidate fix must clear: mechparts/9 and /11 cylinders > 0, no regression on
   15/8/22, and cadbench normal 73.67 / fine 50.13 unchanged.

## Refuted this session — do NOT retry (each with its measurement)

1. L08_pillow_block 15.06% volume error -- does not exist; 203 normal + 281 fine models all
   within 0.05%. It was the in-memory figure n17 already discredited.
2. The ungated fprintf at refit_fillet.cpp:772 dominating runtime -- 28 lines per run.
3. Seed-triple combinatorial explosion -- mechparts/29 has 367 triples, the FAST corpus
   model L04_pillow has 4,944.
4. n20 law-band seed dedup -- costs mechparts/15 its only cylinder.
5. "ShapeFix opens the shell" -- free edges do not rise across fix.Perform(); it was unify.
6. n21 sagitta/radius gate -- removes 89% of cylinder REGIONS on part 11 (56 -> 6).
   WITHDRAWN from production after being deployed for ~50 minutes.
7. n21 contagion form (drop only when an edge-adjacent cylinder is >=10x finer) -- fires on
   neither model.
8. n22 law-band quorum bypass -- total cylinders 15 -> 27 across 6 parts but two parts go to
   zero; the quorum is load-bearing.
9. U2 cascade brake (n24) -- decideCascade's U2 path never executes on part 9 (0 hits traced).
10. Blanket-explode brake (n26) -- explodes 3,777 -> 157, cylinders stay 0, because refusing
    to explode routes to heal-discard which bins the build.
11. Keeping built faces at heal-discard (n26b) -- fires, but the cylinders were already
    exploded in the first targeted pass. Too late.
12. **n28: raising the 10,000-triangle J6 heal cap (STL2STEP_N28_HEAL_MAXTRI) -- NO EFFECT
    on parts 9 or 11.** The perfect correlation "every part shipping cylinders is < 10k
    triangles" is a coincidence of which parts are small, not causation.
13. "Mass edge-construction failure" -- DIAG_PARTIAL_EDGE is a per-edge TRACE of the
    diagnostic walk (refit_build.cpp:2061), not a failure counter. 11,800 meant 11,800 edges
    examined. Real number: N25_CHAINFAIL chains=11498 **failed=69** regionsHit=129.

## The pattern worth remembering

The engine destroys valid geometry while reacting to small localised faults, and every fix
that has worked was a PROPORTIONALITY fix, not a geometry fix:
 - 0.6% of chains fail (69 of 11,498) -> 3,777 regions exploded, 98 built cylinders lost
 - one 2-triangle 90-degree patch with an honest 2.93 mm sagitta -> four 144-sided bores
   fitting to 0.0002 mm are exploded
 - six plane faces own free edges they did not cause -> free edges 10 -> 152 -> the whole
   collar reverts to facets

Corollary, learned the hard way twice today: every constant in this engine was fitted to
cadbench, whose parts do not resemble the user's. Measure on ~/corpora/mechparts BEFORE
believing a corpus A/B, and order any census by the property under study, never by file size.
