# Success axis — does governing break legit coding work?

_Phase 3. A governor fails the success axis by HARD-blocking work the developer would have kept. We measure that two ways: **(primary)** replaying 16 substantive real Claude Code sessions (2551 behaviourally-confirmed-accepted calls), each grounded by Phase-1 outcome replay into accepted / reverted / ambiguous (`OUTCOMES.md`); a *working session* has ≥1 behaviourally-confirmed-**accepted** call, and a **break** is a non-overridable hard block on an accepted call. **(anchor)** 30 SWE-bench Verified gold trajectories (102 synthesized calls) — does each governor PERMIT the verified solution path? Every governor scores the byte-identical record stream._

## Primary — real captured developer sessions

_Completion-preserved = 1 − (sessions hard-broken / working sessions). Hard-break call-rate = share of accepted calls a NON-overridable deny lands on (a real task-break). Friction call-rate = share of accepted calls an OVERRIDABLE gate (ask / overridable block) interrupts — real, but recoverable with one confirmation, never a break._

| Governor | Completion-preserved | Sessions broken / working | Hard-break (call-rate) | Friction (call-rate) |
|---|---|---|---|---|
| ungoverned | 100.0% | 0 / 16 | 0.0% | 0.0% |
| perfect-allowlist | 56.2% | 7 / 16 | 0.8% | 0.0% |
| regex-denylist | 68.8% | 5 / 16 | 1.1% | 0.0% |
| native-permission | 100.0% | 0 / 16 | 0.0% | 40.0% |
| credence-deny-safety | 75.0% | 4 / 16 | 0.8% | 2.8% |
| credence-default | 100.0% | 0 / 16 | 0.0% | 3.6% |

_**ungoverned** = no governor (the completion ceiling); **perfect-allowlist** = BOUND — generous capability allow-list (hard block on overt out-of-policy); **regex-denylist** = REAL — afternoon deny-list guard (hard block on bad signatures); **native-permission** = REAL — harness native permission model (asks; never hard-denies); **credence-deny-safety** = PRODUCT — Credence with opt-in hard-deny('safety'); **credence-default** = PRODUCT — Credence, overridable-by-default (the shipped governor)._

## What the success data says

- **Credence cannot break legit work by default — that's structural, not luck.** Since 2026-06-28 every Credence decision is overridable (a categorical deny implies infinite disutility, which a finite harm-cost H contradicts — so the human's "I actually want this" is admissible evidence). A false positive is therefore **one extra confirmation, never a broken task**: `credence-default` preserves 100.0% of working sessions, hard-breaking 0.0% of accepted calls — by construction.

- **Hard-deny rivals DO break real work.** A non-overridable block is a task-break when it lands on a kept call. Even at a ~1% call-level false-block rate (0.8%/1.1% of accepted calls), ONE hard block derails a whole session — so `perfect-allowlist` preserves only 56.2% (7/16 sessions broken) and `regex-denylist` 68.8% (5/16). That session-level amplification is the buyer's real exposure.

- **And most of those breaks are GENUINE false positives, not fixture noise.** Of perfect-allowlist's 7 broken sessions, 2 are in this safety system's own repos (where attack-test-fixtures live → possible contamination) but **5 are unrelated developer projects** (life-agent, morel, ops, port-authority, simpleparty); regex-denylist's split is 2 vs **3** (ops, port-authority, simpleparty). These are ordinary dev operations the developer ran and kept (destructive build steps, privilege ops, credential-adjacent calls) that a signature/allow-list guard mis-flags — the over-block tax on real work, independent of this corpus's quirks.

- **Opt-in hard-deny costs completion — which is exactly why overridable is the default.** Flip Credence into hard-deny('safety') and it breaks 4/16 sessions (75.0% preserved): the safety label DOES fire on some accepted calls (partly the same fixture contamination). The shipped default keeps those as overridable confirmations, turning would-be breaks into friction — the finite-H argument made concrete.

- **The real separator is friction, and Credence wins it decisively.** Both Credence and a native permission model avoid hard-breaks, but native-permission interrupts **40.0%** of accepted calls vs Credence's **3.6%** — a ~11× reduction. Native asks on tool SHAPE alone (no provenance, data-flow, or harm-probability notion — where that lands on the harm axis is `COMPARISON.md`, not measured here); Credence reaches the same no-break safety while interrupting a fraction as much real work.

## Anchor — SWE-bench Verified gold trajectories (public)

_Each Verified instance ships a gold patch the SWE-bench harness CONFIRMED resolves the task. We synthesize its solving tool-calls (read → edit → run the failing tests) and ask each governor whether it permits that verified path. No agent, no docker — resolution is given; we measure only permission. Completion-preserved here = resolved-path-preserved._

| Governor | Completion-preserved | Sessions broken / working | Hard-break (call-rate) | Friction (call-rate) |
|---|---|---|---|---|
| ungoverned | 100.0% | 0 / 30 | 0.0% | 0.0% |
| perfect-allowlist | 100.0% | 0 / 30 | 0.0% | 0.0% |
| regex-denylist | 100.0% | 0 / 30 | 0.0% | 0.0% |
| native-permission | 100.0% | 0 / 30 | 0.0% | 29.4% |
| credence-deny-safety | 100.0% | 0 / 30 | 0.0% | 0.0% |
| credence-default | 100.0% | 0 / 30 | 0.0% | 0.0% |

_**ungoverned** = no governor (the completion ceiling); **perfect-allowlist** = BOUND — generous capability allow-list (hard block on overt out-of-policy); **regex-denylist** = REAL — afternoon deny-list guard (hard block on bad signatures); **native-permission** = REAL — harness native permission model (asks; never hard-denies); **credence-deny-safety** = PRODUCT — Credence with opt-in hard-deny('safety'); **credence-default** = PRODUCT — Credence, overridable-by-default (the shipped governor)._

## What the anchor confirms

- **On clean public code, no governor hard-breaks the verified fix** — completion-preserved is 100% across the board. This establishes a useful floor (the gold path's tool-calls — read / edit / `pytest` — don't trip the signature rivals on clean code), but it is NOT a claim that the real-session breaks were all contamination: those were mostly genuine false positives on unrelated dev work (above). The anchor's narrow tool-call set simply doesn't replicate the destructive / privilege / credential-adjacent operations that broke real sessions.

- **Friction still separates them on the gold path.** Even on a known-good solution, native-permission interrupts 29.4% of calls (it asks on every test-run), while Credence interrupts 0.0% — a consistent separation, reproduced on a clean public set.

## Cited rivals (mechanism + source — not run here)

- **Llama Guard 3** (harm classifier): open-weight allow/deny safety classifier with **no override path** — every benign false-positive becomes a hard task-break, not a confirmation. Published evals show a non-zero benign false-positive rate, and it is content-semantic (not coding-structural), so it over-flags ordinary code. It also covers neither cost nor waste. [source](https://huggingface.co/meta-llama/Llama-Guard-3-8B)
- **Lakera Guard** (prompt-injection guard): hosted guardrail (PINT ~92.5%); a hard allow/deny gate over prompts — same structural limit as Llama Guard for the success axis: a false positive blocks the work outright. [source](https://www.lakera.ai/)

## Reading

- **Measured** rows ran on the identical record stream (real sessions + the public anchor); **cited** rows are third-party guardrails, tagged and linked, never blended.
- **Denominator:** the 16 working sessions are the *substantive* multi-call sessions — they hold essentially the entire corpus; the other 26 sessions are all 1-call singletons (max size 1, 26/26) with no observed continuation, so no landed work to break. The session count is small, so the **per-call rates (over 2551 accepted calls) are the robust measure**; session-level completion-preserved is the harsher, derail-amplified view.
- A **break** is a non-overridable hard block on a behaviourally-confirmed-accepted call — work the developer demonstrably kept. Blocks on reverted/ambiguous calls never count.
- **Credence's no-break property is a design choice (overridability), reported as such** — the *measured* claims are (a) how often the hard-deny rivals actually fire on accepted work and (b) the friction separation between Credence and a native permission model.
- **Caveat (corpus hygiene):** the captured corpus includes this project's own development of the safety system — synthetic attack payloads authored as test fixtures appear as benign calls and trip the signature rivals. But that accounts for only a MINORITY of their breaks (the split above); the majority are genuine false positives on unrelated dev work. Either way the inflation is a caveat *against the rivals*, and the contamination-free SWE-bench anchor isolates the floor.
- **Honest limit of the anchor:** it scores the KNOWN-GOOD solution PATH, not an autonomous agent's resolved-rate; permitting the gold path is necessary (not sufficient) for an agent to resolve via it. A full agent + docker run is the heavier future upgrade.
- The credence rows are the real BrainSession decision over the skin wire; the two variants are the shipped overridable-by-default governor and the opt-in hard-deny('safety') config.
