# Governance roadmap: proplang as the decision core for coding agents

Status: adopted 2026-07-10 (Phase 0 in execution). Owners are marked per phase:
"builder" = work that can proceed on unfrozen surfaces without a proplang boundary;
"author" = an act only the proplang author can perform (a ruling, a metric
registration, an oracle-first freeze). This document is descriptive of the joined
programme; it binds nothing in the proplang repository — every proplang boundary
named here opens only by the author's signed tag, under the discipline the
HOSTS_D_PACK register records (R-D20 copy-not-reconstruct, R-D21 satisfiability
transcripts, R-D22 delegated-edit re-tags, R-D23 declared segmentation).

## Why this document exists

The original motivation for the proplang hosts programme (HOSTS_PLAN §0.1) is a
Bayesian decision core "whose every prior is the alphabet, whose every constant is
priced, and whose reasoner cannot be steered — credence-governor's tool-call gate
today." The language side is delivered: increments H (the governor host driver) and
D (the latent-utility pilot, outcome-grounded) are closed under author tags
(`h-close`-era freezes through `d-close`), and `proplang-govhost` speaks both wire
generations — `table@1` (declared step-table utility) and `latent@1` (learned
utility over declared channels).

What is NOT yet true is the thing the programme was for: the governor on this
machine — `credence-governor.service`, ~30k real Claude Code decisions — decides
entirely on the Julia credence-skin engine, and **in shadow mode**
(`CREDENCE_GOVERNOR_SHADOW=1`: the hook narrates "would block", never enforces),
demoted from enforcement because it blocked too often. The proplang path exists
only as `membrane.py`'s shadow `MembraneSession` (table@1, waste-only, never wired
into `run()`). This document is the path from that state — an advisory engine
nobody lets enforce — to proplang actually governing.

## The first outcome-scored reading (2026-07-10, shadow counterfactuals)

Shadow mode has one great virtue: every decision has a realized counterfactual —
the tool ran regardless, so grounded outcomes score the decisions directly. The
Phase-0 grounding backfill (29,455 outcome records over the 60 GB capture) gives
the incumbent engine its first outcome-scored reading:

| Shadow decision | Grounded | Accepted (kept) | Reverted | Ambiguous |
|---|---|---|---|---|
| proceed (24,023) | 23,485 | 12,398 | **10** | 11,077 |
| block (6,436) | 5,672 | 2,570 (45%) | **0** | 3,102 |
| ask (342) | 304 | 169 | 0 | 135 |

The would-block rate is **21%** — the "blocked too often" that got enforcement
turned off, now quantified. Of 5,672 grounded would-blocks, **not one** was
reverted, and 45% were plainly accepted (completed, kept). Caveats: "ambiguous"
is the structural classifier's can't-tell bucket, and acceptance does not strictly
disprove a *waste* label (a kept call can still have been low-value) — but as
justification for blocking, the outcome evidence is currently zero. This table is
exactly the shape the Phase-1 bench formalizes, and the baseline any challenger
engine has to beat.

## The blocker structure (read this before the phases)

Two facts jointly determine the ordering:

1. **R-D14, the acceptance-metric interregnum** (proplang HOSTS_D_PACK register):
   the membrane has no registered acceptance metric. Decision-agreement-% against
   the Julia engine was retired as an acceptance standard (it measures conformity
   to the incumbent, not quality); the outcome-scored bench that replaces it "needs
   observables that do not exist yet." Until the interregnum closes, no promotion
   decision can be principled — there is nothing to promote *on*.

2. **The missing observables are already written.** The `/result` endpoint, the
   PostToolUse correlation hook, and the `ground_capture` backfill CLI exist on
   `feat/membrane-adapter`, tested but unmerged and undeployed. Production
   consequence: 8 human verdicts and 0 outcome records across ~30k decisions — the
   learning loop is open exactly where D's doctrine (O3) says the primary evidence
   lives: outcomes, the responder-free ground truth, with verdicts only the noisy
   myopic proxy.

So the critical path runs through **deployment and measurement**, not new language
work. The remaining proplang increments stay demand-gated behind what the
measurements show (HOSTS_PLAN §9).

## Phase 0 — merge and deploy the observables (builder; in execution)

Merge `feat/membrane-adapter`; deploy the outcome plumbing to the live daemon;
install the PostToolUse hook; run the grounding backfill over the raw capture
(before any rotation — the capture is the backfill source); implement the R-D16
retention policy (inventory, rotate + compress the grounded backlog, 90-day raw
window matching the grounding window, `observations.jsonl` kept indefinitely,
capture bounded by `CREDENCE_GOVERNOR_CAPTURE_MAXLEN`).

Exit criterion: `observations.jsonl` accumulates linked `outcome` records for both
live traffic (PostToolUse) and the historical backlog (grounding) — R-D14's missing
observables exist and keep arriving.

## Phase 1 — the outcome-scored bench closes R-D14 (builder drafts; author registers)

Build the bench that scores governance decisions against grounded outcomes —
reverted / retries / completed / spend, valued in the engine's own loss units (the
buyer-loss shape of `benchmarks/governor_compare/INTEGRATED.md`) — instead of
decision-agreement. The bench is builder work on unfrozen surfaces; **registering
it as the membrane's acceptance metric is an author document act**, and is the
natural bundle with the items already queued for the next author boundary: the
deference-floor doctrine amendment (HOSTS_D_PACK §6 / HOSTS_PLAN 6.1, falsified by
the frozen gHeadline table), CLAUDE.md canonization of R-D20/21/22, and the
test-membrane locale fix.

Exit criterion: the interregnum line on the register closes — the membrane's field
performance is measurable by a registered standard.

The bench also defines the **exit from shadow mode**: enforcement was turned off
because the incumbent blocked too often, and it comes back per-category only when
an engine's false-block rate on grounded outcomes clears a declared bar. That makes
"the governor is allowed to govern again" a measured milestone, not a mood.

## Phase 2 — the membrane shadows live traffic on latent@1 (builder; admissions author's)

Wire `MembraneSession` as a shadow beside every live decide, and upgrade the
adapter's handshake from `table@1` to `latent@1`: declare `said`, `residuals`,
`tau`, `price`, and `gauge` per membrane-wire.md §6 (the shape the govhost latent
handshake golden pins). Feed stream-tagged evidence — `verdict` from `/feedback`,
`outcome` from grounded records, `report` from features — and warm-boot each
session via `observe_counts` (measured at D's close: 11.4 ms for ~39k collapsed
ticks; live ticks 8.26 ms, engine-dominated — latency-viable at hook speed).
Segmentation of any warm collapse is host-declared data, never a tuned knob
(R-D23). The adapter never branches on `residual_mean`/`sensitivity` — those are
observability-only; routing to elicitation happens engine-side by argmax.

Score BOTH engines on the Phase-1 metric over the same traffic; keep
`membrane_diff`'s agreement gate only as a shadow sanity check. Measure the live
ask-rate against the recorded field prediction (hosts-d-task3-report §2a: the
governor under this utility model asks rarely, through the verdict channel,
essentially only at decision boundaries — the field's number confirms or falsifies
a stated prior). The incumbent's measured 21% would-block rate with zero
outcome-justified blocks is precisely the shortfall shape the membrane's
VoI-priced asking is predicted to avoid — Phase 2 is where that prediction meets
the same traffic that demoted the incumbent.

Exit criterion: a shadow window long enough to compare engines on the registered
metric, plus the ask-rate reading.

## Phase 3 — the A gate decision (author)

Increment A (options-as-data, K-ary observation carriers) opens only on measured
demand: HOSTS_PLAN §9's gate is the life-agent/membrane differential vs the
credence brain. For the coding host the demand would look like: menus beyond
{ask, block, proceed} — candidate-action selection, model routing as priced
options — or K-ary evidence the binary verdict carrier cannot express. Phase 2's
differential either surfaces that shortfall, measured, or it doesn't. If it does,
the author opens A's oracle-first boundary; if not, A stays closed and the stack
ships as-is. (A's design is drafted in HOSTS_PLAN §4 so the gate decision is cheap.)

## Phase 4 — promotion to primary (author ruling)

Conditions, all three: (a) the membrane meets or beats the Julia engine on the
registered outcome metric over a declared shadow window; (b) a backend-selection
change in `run()` (today `BrainSession` is constructed unconditionally); (c) any
harm-channel admission — epoch 2 — is a per-source author ruling (R-D3; epoch 1 is
waste-only by construction). Plausible first slice: membrane primary for waste
decisions with the Julia harm overlay retained, then full promotion with Julia
demoted to shadow. Rollback at every step is a config change, not a rebuild.

## Phase 5 — demand-gated B and C (author boundaries)

- **B, the reliability channel** (HOSTS_PLAN §5): built only if A's differential
  shows a correlated-evidence / reliability-learning shortfall. Its coding-agent
  demand shape is exactly LLM-judge or flaky-reviewer verdicts: a per-document
  reliability latent ρ learned by inference, so unreliable verdict sources become
  channels whose trustworthiness is estimated rather than declared, and correlated
  evidence is deduplicated by the model rather than by host-side heuristics.
- **C, arithmetic** (HOSTS_PLAN §7): built only on measured step-table underfit,
  ablation-grade. Arithmetic is deliberately not cheap; step tables remain the
  cheap spelling.

Neither is scheduled. Both are drafted so the gate decisions cost a reading, not a
design effort.

## References

- proplang (frozen programme): `HOSTS_PLAN.md` (§0.1 motivation; §4 A; §5 B; §7 C;
  §9 gated roadmap), `HOSTS_D_PACK.md` (rulings register, R-D14/R-D16/R-D20–23),
  `membrane-wire.md` (the normative wire, v1 §1–5, v2/latent §6),
  `hosts-d-task3-report.md` (§2a field prediction; §5 measured wall-clock).
- credence-governor (unfrozen host): `packages/governor_core/credence_governor_core/
  membrane.py` (the adapter), `training/membrane_diff.py` (shadow differential),
  `training/ground_capture.py` + `training/outcomes.py` (grounding),
  `docs/engine-wire-requests.md` (Julia-engine wire proposals — parallel track),
  `benchmarks/governor_compare/` (the measured product baselines).
