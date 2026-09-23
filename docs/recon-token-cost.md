# AI rebuild (recon) — measured token cost per object

Measured 2026-09-23 from every recon Claude Code transcript on both nodes
(`~/.claude/projects/-tmp-mesh2step-<id>-recon-m1-opus/*.jsonl`, 2026-09-22 03:26Z → 2026-09-23 13:09Z)
joined to `SRVRECON` journal lines. Read-only analysis; no model call was made.
All transcripts predate the MCP fix (`77ad61d`, committed 13:14Z), so none measures the post-fix state.

**Labels.** *Measured* = summed from `message.usage` in the transcripts. *Derived* = computed from
measured data plus a stated assumption. *Published* = quoted from an Anthropic page (URL given).
*Not published* = I looked and Anthropic does not state it.

## 0. Method (so the numbers can be re-run)

- One recon dir = one object; one `.jsonl` = one `claude -p` call = one round.
- Each call is itself an agent loop (median 10 API requests per call). Claude Code writes one
  jsonl line per content block, each repeating the request's `usage`, so usage is **deduplicated by
  `message.id`**. Fields: `input_tokens`, `output_tokens` (includes `output_tokens_details.thinking_tokens`),
  `cache_creation_input_tokens` (split in `cache_creation.ephemeral_5m/1h_input_tokens`),
  `cache_read_input_tokens`.
- `<synthetic>` assistant messages are limit refusals (no tokens) and are counted separately.
- Join to outcome: an object matches the `SRVRECON <dur> status=…` line on the same host whose
  `[T−dur, T]` window (±180 s) contains all its calls.
- Cross-check: total recon $ computed per request over the whole account log ($358.72 over 2 592
  requests) equals the per-object sum ($358.72, 2 592 requests). The two median objects were
  re-priced by hand from their token totals and match to the cent.

## 1. Population

| | nativedev | behemoth | total |
|---|---|---|---|
| recon dirs | 111 | 55 | 166 |
| **completed objects (no call refused) — the statistics base** | 72 | 16 | **88** |
| partially refused by the usage limit | 4 | 0 | 4 |
| every call refused by the usage limit (0 tokens) | 37 | 37 | 74 |
| `claude -p` calls with tokens | 174 | 66 | 240 (235 in the 88) |

Model actually served for `--model opus`: nativedev `claude-opus-5-5` (137 calls) and `claude-opus-5`
(37 calls, 2026-09-22 before its CLI update); **behemoth `claude-opus-5` for all 66 calls**.

Outcome of the 88 (SRVRECON join): accepted 43, best_effort 19, failed 18, unmatched 8.
(The 18 `model=reverse` accepts made no model call and are not in this data.)

## 2. Per object — measured (n = 88 completed objects, both hosts)

| per object | median | p90 | max | mean |
|---|---|---|---|---|
| calls (rounds) | 2 | 5 | 5 | 2.67 |
| API requests | 25 | 62 | 89 | 29.1 |
| input (uncached) tokens | 50 | 124 | 178 | 58 |
| output tokens (72.6 % of them thinking) | 29 910 | 155 598 | 389 164 | 61 961 |
| cache-write tokens (99.5 % are 1-hour writes) | 163 296 | 460 791 | 656 539 | 212 148 |
| cache-read tokens | 1 316 753 | 4 542 875 | 9 564 074 | 2 050 568 |
| all tokens | 1 688 384 | 5 005 210 | 10 094 224 | — |
| **API-equivalent cost** | **$2.59** | **$9.29** | **$15.18** | **$3.97** |
| model wall time, s (sum of call spans) | 405 | 1 804 | 4 765 | 829 |

Cache hit rate (read / all input) is already 90.6 %. Cost split: **cache writes 47.2 %, output 36.0 %,
cache reads 16.8 %, uncached input 0.0 %.** Per call: median $1.13, p90 $2.96 (n = 235).

By subset (API-equivalent $/object, median · p90 · max · mean):

| subset | n | median | p90 | max | mean |
|---|---|---|---|---|---|
| nativedev | 72 | 2.07 | 6.92 | 10.32 | 2.96 |
| behemoth | 16 | 9.81 | 14.67 | 15.18 | 8.52 |
| accepted | 43 | 1.16 | 4.98 | 8.94 | 2.00 |
| best_effort | 19 | 5.35 | 8.59 | 13.55 | 5.43 |
| failed | 18 | 6.73 | 12.15 | 14.67 | 6.79 |
| ran all 5 rounds | 27 | 5.58 | 11.37 | 14.67 | 6.78 |
| **current config** (started after Bash was denied, `cd29589`, ≥06:25Z 09-23) | 21 | **3.16** | **13.55** | 15.18 | **4.98** |

Per call, nativedev costs $1.24 and behemoth $2.16: behemoth runs the older, pricier Opus 5 and emits
~2.8× the output per call (43.8k vs 15.7k tokens).

**Cost per *accepted* rebuild** (derived): all recon spend $358.72 / 43 accepted = **$8.34**.
65 % of spend went to objects that did not end accepted (best_effort 29.6 %, failed 35.0 %,
unmatched 10.8 %). Cost by round index: round 1 39.2 %, 2 26.5 %, 3 17.5 %, 4 9.1 %, 5 7.8 %.
Of 43 accepts, 28 came in round 1, 40 by round 3, 3 needed round 4–5.

## 3. Dollar prices used

Source: https://platform.claude.com/docs/en/about-claude/pricing (fetched 2026-09-23), USD / MTok:

| model id in transcripts | input | 5 m write | 1 h write | cache read | output |
|---|---|---|---|---|---|
| `claude-opus-5-5` (Opus 5.5) | 4 | 5 (1.25×) | 8 (2×) | 0.20 (0.05×) | 20 |
| `claude-opus-5` (Opus 5) | 5 | 6.25 (1.25×) | 10 (2×) | 0.50 (0.1×) | 25 |

No long-context surcharge (1M context at standard price); `inference_geo` was `not_available`, so no 1.1×.
These are also the prices you actually pay on a Max plan once the included allowance is spent:
"Usage credits are billed at standard API rates"
(https://support.claude.com/en/articles/12429409-manage-usage-credits-for-paid-claude-plans).

## 4. MCP overhead — derived

The first request of every call carries a fixed harness prefix. Measured first-request prompt size
(input + cache write + cache read): nativedev ~47–55k tokens, behemoth ~24–27k. Attachment sizes in that
request (chars, from the latest transcript on each host):

| component | nativedev | behemoth |
|---|---|---|
| MCP deferred-tool list (210 / 82 MCP tool names) + MCP server instructions | 24 492 | 9 845 |
| skill listing | 33 237 | 19 434 |
| `~/.claude/CLAUDE.md` (instructions) | 27 023 | — (none on behemoth) |
| hook output (SessionStart etc.) | 19 167 | — |
| the recon prompt itself | 10 401 | 9 430 |

Calibration (derived): solving the two hosts' first-request token counts against their attachment chars
gives 3.15 chars/token and a ~9.2k-token Claude Code base prompt, consistent with the measured shared
cache read of ~10k on every first request. Hence **MCP ≈ 7.8k tokens/call on nativedev, 3.1k on behemoth;
the whole non-task harness (MCP + skills + CLAUDE.md + hooks) ≈ 33.0k and 9.3k**. Claude Code already
defers MCP tool schemas (names only), which is why MCP is a small part. Uncertainty ±30 % on these splits.

Removing a prefix of X tokens saves, per call, X × 1 h-write price + X × (requests−1) × read price:

| scenario (n = 88) | median | p90 | max | mean | Δ mean |
|---|---|---|---|---|---|
| as measured | $2.59 | $9.29 | $15.18 | $3.97 | — |
| MCP removed (the fix in `77ad61d`) — derived | $2.49 | $9.07 | $14.99 | $3.77 | −5 % |
| whole harness prefix removed — derived | $1.65 | $8.64 | $14.63 | $3.14 | −21 % |
| current-config subset (n = 21): measured / MCP removed / harness removed | $3.16 / $2.81 / $1.67 | $13.55 / $13.36 / $12.99 | | $4.98 / $4.76 / $4.07 | |

The fix mainly buys safety (no MCP tool bypassing `--disallowedTools`, no Serena launches); its token
saving is ~5 %.

## 5. Max plan fraction

**Published** (fetched 2026-09-23):
- Max 5x = "five times the Pro plan's per-session usage allowance", Max 20x = 20 times; "session-based
  usage limit will reset every five hours"; "Max plans also have a weekly usage limit that applies across
  all models" — https://support.claude.com/en/articles/11049741-what-is-the-max-plan
- claude.com/pricing: "5x / 20x more usage than Pro" per session, "usage limits apply", no number.
- Anthropic, 2026-05-06: Claude Code five-hour limits doubled for Pro/Max — https://www.anthropic.com/news/higher-limits-spacex
- **Not published:** any token, dollar, message or hour figure for the 5-hour window or the weekly limit.
  (The old "≥225 / ≥900 messages per 5 h" article, support 11014257, now returns 404; I do not use it.)

**Measured on this account.** The account is Max 5x (`rateLimitTier: default_claude_max_5x`) with extra
usage enabled. Its monthly extra-usage cap was already exhausted at 2026-09-21 14:25Z, so every refusal
since is the included 5-hour allowance running out. Refusal text: "You've hit your monthly spend limit …
your session limit resets <time>". Four 5-hour windows were exhausted in 24 h, and recon was the majority
consumer in each (API-equivalent $ consumed on both nodes from window start = reset − 5 h to first refusal):

| window (UTC) | first refusal | total consumed | recon | everything else |
|---|---|---|---|---|
| 09-22 13:40 → 18:40 | 17:52 | $128.00 | $68.27 | $59.72 |
| 09-22 23:40 → 09-23 04:40 | 03:18 | $89.30 | $79.09 | $10.21 |
| 09-23 04:40 → 09:40 | 07:44 | $120.91 | $70.16 | $50.75 |
| 09-23 09:40 → 14:40 | 12:53 | $75.43 | $65.33 | $10.10 |

This is a **lower bound** on window capacity (usage from other machines and claude.ai is not in these
logs) and assumes the plan meters roughly in proportion to API price, which Anthropic does not state.
Observed: **one Max 5x 5-hour window ≈ $75–128 API-equivalent.** The refusals also blocked the owner's
interactive sessions (the refusal messages appear in both recon and non-recon transcripts), and 74 objects
got no rebuild at all.

Per-object fraction of one 5-hour window (derived; 20x taken as 4× the 5x window, per the published multiples):

| object cost | Max 5x (window $75–128) | Max 20x (window $300–512) | objects per 5x window |
|---|---|---|---|
| median $2.59 | 2.0–3.5 % | 0.5–0.9 % | 29–49 |
| mean $3.97 | 3.1–5.3 % | 0.8–1.3 % | 19–32 |
| p90 $9.29 | 7.3–12.4 % | 1.8–3.1 % | 8–14 |
| max $15.18 | 11.9–20.2 % | 3.0–5.1 % | 5–8 |

**Weekly fraction: cannot be given.** The weekly limit is not published and was never hit in this data
(no weekly-limit refusal), so there is nothing to measure it against. For scale: the configured ceiling of
50 objects/day/node × 2 nodes × mean $3.97 ≈ $397/day API-equivalent, i.e. ~3–5 exhausted Max 5x windows
per day from recon alone — consistent with what was observed.

## 6. Top 3 levers (ranked by expected saving)

1. **Stop spending on objects that will not be accepted** — addresses 65 % of spend (best_effort + failed +
   unmatched) and the 61 % of cost that sits in rounds 2–5. Measured floor: capping at 3 rounds cuts
   **−17 %** (rounds 4–5 = 16.9 % of cost) and loses 3 of 43 accepts. An abort-on-no-progress after round
   2 would reach further into the 65 %; its effect on the accept rate is not measured.
2. **Strip the harness prefix from each `claude -p` call** (CLAUDE.md, skill listing, hook output, MCP) —
   cache writes are 47 % of cost and the ~33k-token prefix is re-written at the 2× one-hour price on every
   call, then re-read on every request. Derived saving **−21 % mean, −36 % median**; MCP alone (done) is −5 %.
   Same bucket, quick: make behemoth resolve `opus` to Opus 5.5 like nativedev (20 % lower list price,
   60 % cheaper cache reads; behemoth's $/call is 1.7× nativedev's). If the rebuild ever moves to the API
   directly, 5-minute instead of 1-hour cache writes would save a further −18 % (derived).
3. **Cap thinking/effort** — thinking is 72.6 % of output tokens and output is 36 % of cost, so thinking ≈
   **26 %** of cost. Upper bound; the quality effect of a lower budget is unmeasured, which is why this ranks
   third despite the larger share.

## 7. Bottom line

Measured today, one AI rebuild costs a median **~1.7M tokens / $2.59** API-equivalent (mean $3.97,
p90 $9.29, max $15.18; current config median $3.16, mean $4.98, p90 $13.55), and because 65 % of spend
lands on rebuilds that are not accepted, **each accepted rebuild costs $8.34**. The MCP fix alone takes the
mean to ~$3.77 (−5 %); stripping the whole harness prefix to ~$3.14. At $9 charged per object attempted,
the mean is covered ~2.4× with the fix, but p90 objects (≥$9.29, $13.55 in the current config) lose
money; at $9 charged only per accepted rebuild, the margin is ~8 % — effectively none. $9 becomes safe only
with a hard per-object spend cap (~$4–5 abort) plus lever 1. On the Max 5x plan, recon alone exhausted four
5-hour windows in 24 h (each ≈ $75–128 API-equivalent), so the plan cannot carry this feature at volume;
priced honestly it must be costed at API rates. Separately, check Anthropic's consumer terms before
serving paying third parties from a personal Max subscription.
