# The capstone — which governor should a buyer actually pick?

_Phase 4 integrates the three measured axes — **cost** (Phase 2, `COST.md`), **harm** (Phase 1, `COMPARISON.md`), **success** (Phase 3, `SUCCESS.md`) — over the buyer tradeoff profiles (`profiles.py`, drift-guarded vs the shipped `profile.ts`), in the product's OWN Wald currency: a destroyed task costs `λ·reward`, an interruption costs `q`, a leaked attack costs the harm price `H`. Nothing is re-measured here; the per-axis numbers are the committed phase results (`axes_summary.json`, source-tagged)._

_**The buyer ships tasks, not tool-calls.** Phase 3's load-bearing finding: one non-overridable block doesn't waste one call — it derails the whole session. So the benign loss is driven by **completion-preserved** (session-level), which is why hard-deny rivals at a ~1% per-call block rate still destroy **31–44% of real tasks**. The integrated loss is therefore per-task; the friction term uses the real-corpus **mean 159 calls/task** — far heavier than typical benchmark tasks (SWE-bench gold ≈ 3.4 calls), so a conservative friction anchor that works against Credence; shorter tasks only lower its break-even further._

## 1. Coverage — most rivals are point solutions

| Governor | Cost | Harm | Success | Waste |
|---|---|---|---|---|
| ungoverned | — | — | ceiling | — |
| perfect-allowlist | — | ✓ (bound) | ✓ | — |
| regex-denylist | — | ✓ | ✓ | — |
| native-permission | — | ✓ (asks) | ✓ | — |
| llm-judge | — | ✓ | (breaks) | — |
| routellm-style | ✓ | — | — | — |
| credence-deny-safety | ✓ | ✓ | ✓ | ✓ |
| credence-default | ✓ | ✓ | ✓ | ✓ |

_Only **Credence** (both configs) spans all four axes; every rival scores **—** on the axes it ignores — and **—** is not neutral, it is *unbounded* loss there (RouteLLM lets every attack through; a harm guard has no routing and no waste view). A buyer who needs >1 axis must stack point tools or pick the one governor that already spans them (2 of 8 rows do)._

## 2. When is a governor worth turning on? (break-even attack rate)

_The ungoverned baseline's only loss is unmitigated harm (`π·H`). A governor earns its keep once the buyer's attack exposure `π` exceeds the point where its friction + any task-destruction is repaid by the harm it averts: `π* = B / (B + recall·H)`. **Lower = worth deploying sooner.** The first governor to cross break-even as risk rises is the one to buy._

| Profile | perfect-allowlist | regex-denylist | native-permission | credence-deny-safety | credence-default |
|---|---|---|---|---|---|
| cost-saver | 0.4% | **0.3%** | 79.9% | 24.3% | 32.4% |
| balanced | 46.7% | 40.9% | 61.5% | 32.6% | **16.1%** |
| quality-first | 81.4% | 77.6% | 79.9% | 67.8% | **32.4%** |
| speed-first | 46.7% | **40.9%** | 97.6% | 78.0% | 82.7% |
| indie-hacker | 1.7% | **1.4%** | 86.4% | 34.1% | 43.4% |
| startup-balanced | 46.7% | 40.9% | 61.5% | 32.6% | **16.1%** |
| regulated-enterprise | 58.4% | 52.6% | 38.9% | 38.4% | **7.1%** |
| fintech-safety | 74.5% | 69.8% | 34.7% | 55.2% | **6.0%** |
| quality-research | 81.4% | 77.6% | 44.4% | 64.9% | **8.7%** |

_**Credence-default is the first governor worth turning on in 6 of 9 profiles** — every mainstream and safety-critical one (balanced, fintech-safety, quality-first, quality-research, regulated-enterprise, startup-balanced). It crosses break-even soonest because, uniquely, it adds harm coverage WITHOUT destroying tasks (the rules) or flooding the developer (native). A zero-friction rule wins only the corner profiles — near-zero task value (cost-saver, indie-hacker) or the interruption-optimised preset (speed-first, q≥0.25 — e.g. a CI pipeline, where per-interruption cost dominates) — where any friction outweighs a 31–44% task-destruction rate, so the rule 'wins' by accepting that destruction (with no calibrated probability signal — a blunt hard deny — and lower attack recall, 45–50% vs credence-default's 60%). The friction anchor here is the corpus-mean 159 calls/task; on shorter tasks Credence's break-even falls further below the rivals'._

_**Robust to the pessimistic avert bound.** If only non-overridable denies avert — the developer overrides every flag, attacks included (`harm_averts=hard`, crediting credence-default with just its 25% hard-deny, not its 60% catch) — its break-even rises (balanced 31%) but it still leads every rival in 6 of those 6 profiles. Native-permission, which only ever asks, then averts nothing and never pays at all; the rules are unchanged (their blocks were always hard). So the headline is not an artefact of the charitable assumption._

## 3. Dominance across the realistic profile region

_Fraction of the realistic region (`harm ∈ [0.5,3]`, `λ ∈ [0.25,4]`, uniform — `profiles.py REALISTIC_REGION`) each choice is the min-loss pick, holding the other dials at the `startup-balanced` persona, as attack exposure `π` rises. Includes **ungoverned** so the 'govern at all?' boundary is explicit._

| π (attack rate) | ungoverned | perfect-allowlist | regex-denylist | native-permission | credence-deny-safety | credence-default |
|---|---|---|---|---|---|---|
| 0.5% | 100% | 0% | 0% | 0% | 0% | 0% |
| 2.0% | 100% | 0% | 0% | 0% | 0% | 0% |
| 5.0% | 100% | 0% | 0% | 0% | 0% | 0% |
| 10.0% | 47% | 0% | 1% | 0% | 0% | 51% |
| 20.0% | 14% | 0% | 0% | 0% | 3% | 83% |

_Read across a row: at low exposure the **ungoverned** ceiling owns the region (rare attacks don't repay any friction — the honest Wald answer, and Credence supports it via its low-friction config). As `π` rises, **credence-default** takes over the region — it is the governance choice that dominates once governing is warranted, while the hard-deny rivals never own a meaningful share (their task-destruction outweighs their catch over this region)._

## 4. Cost — a tie, and that's the honest read

_On coding, cheap ≈ strong (Phase 2): `always-haiku` 95.4% pass at $0.1119 vs `credence@cost-saver` 95.2% at $0.1159 — a statistical tie (overlapping ±std over 25 splits). No realisable router beats always-cheap because a prompt-length difficulty signal can't pick the few hard tasks to upgrade. Credence **matches** the cheap frontier; it does not beat it. The cost edge is **coverage** — Credence reaches this frontier AND governs harm AND preserves tasks; RouteLLM/FrugalGPT are cost-only and score **—** on every other axis (§1)._

## 5. Pareto frontier (governance axes)

_Raw axes, lower-is-better: **leak** (1−attack-recall), **break** (hard-block rate), **friction** (overridable-interrupt rate), **$**/decision. A governor off the frontier is strictly worse than another on every axis._

| Governor | leak | break | friction | $/dec | frontier? |
|---|---|---|---|---|---|
| llm-judge | 0.10 | 0.0950 | 0.0000 | 0.00027 | ✓ |
| native-permission | 0.20 | 0.0000 | 0.3164 | 0.00000 | ✓ |
| credence-deployed@safety-strict | 0.30 | 0.0112 | 0.0316 | 0.00000 | ✓ |
| credence-deployed@shipped | 0.40 | 0.0088 | 0.0272 | 0.00000 | ✓ |
| perfect-allowlist | 0.50 | 0.0105 | 0.0000 | 0.00000 | ✓ |
| regex-denylist | 0.55 | 0.0115 | 0.0000 | 0.00000 | dominated |
| credence-deployed@low-friction | 1.00 | 0.0000 | 0.0000 | 0.00000 | ✓ |

_The frontier is multi-dimensional, so most governors are on it — the profile picks the point. The discriminator is therefore §1–§3, not raw Pareto. Still, one real deployed rival is strictly dominated: **regex-denylist** is strictly dominated by perfect-allowlist; and Credence's configs are all non-dominated (the shipped default and the opt-in `safety-strict` are two frontier points the buyer dials between)._

## 6. Loss triage — every axis Credence is not the single best

- **Cost: tie (capability).** `always-haiku` nominally edges `credence@cost-saver` (within ±std). Cause: the coding regime has no exploitable difficulty gradient (cheap≈strong), so NO router — including the clairvoyant bound's realisable shadow — converts spend into passes. Not a Credence flaw; the headroom isn't there to win.
- **Harm recall: calibration.** Credence catches 60% (+ask) vs `llm-judge` 90% and `native` 80%. But `llm-judge` pays a 9.5% false-block + $/call + 1.0s latency + no override (it *breaks* tasks, §1), and `native`'s 80% is uninformed asks — it interrupts 40% of accepted work (Phase 3) to get there. Credence's catches are harm-flagged and overridable; the recall gap is the allowed-channel class, calibration-improvable without moving the false-block.
- **Break-even corners: by design.** Zero-friction rules win the near-zero-`reward` profiles (`cost-saver`/`indie-hacker`) by accepting 31–44% task destruction — a trade only a buyer who barely values tasks would take, and one Credence can match with its `low-friction` config when harm doesn't matter either.
- **Low-π region: ungoverned wins (honest).** Below break-even, the right move is to govern lightly or not at all — Credence ships that (the `low-friction`/overridable default), so this is coverage, not a loss.

## Reading

- **harm** — governor_compare_results.json (Phase 1; == COMPARISON.md) — measured, real skin
- **cost** — cost/cost_results.json (Phase 2; == COST.md) — measured offline on committed grid
- **success** — SUCCESS.md (Phase 3, PR #18) — PINNED (live-capture grounding not byte-reproducible)
- **profiles** — benchmarks/approach_dominance/profiles.py (PRESETS ∪ PERSONAS, drift-guarded vs profile.ts)
- **Measured vs pinned vs cited:** harm + cost are recomputed from their phase JSONs; success is **pinned** to the merged SUCCESS.md because its grounding reads the live capture and a re-run drifts (16→12 working sessions as the corpus grew) — the qualitative result is identical in both runs, but we never blend a drifted re-run into a committed number.
- **The integrated currency is the engine's own Wald loss** (`config.UTILITY`), so 'lowest buyer loss' is the product's thesis evaluated on real rivals, not a yardstick we invented. The honest finding is two-stage: *should you govern?* (a real break-even, `π*`-dependent) and *if so, which?* (Credence — lowest break-even where governance is warranted, the only full-coverage span, and tunable to match the first answer).
- **Sensitivity reported, not hidden:** the friction anchor (calls/task), the attack rate `π`, and the avert assumption (any-interruption vs hard-deny-only) all move the numbers; the headline uses the least-Credence-favourable friction anchor and still shows the result.
