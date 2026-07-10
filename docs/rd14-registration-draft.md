# R-D14 registration draft — the membrane's acceptance metric (for the author)

Status: DRAFT, builder-prepared 2026-07-10. Nothing here binds until the
author adapts it into the HOSTS_D_PACK register at a proplang freeze
boundary (the natural bundle with the queued items: the deference-floor
doctrine amendment, CLAUDE.md canonization of R-D20/21/22, the
test-membrane locale fix). This document lives in credence-governor only;
the frozen repository is untouched by it.

## 1. What is being registered

**The metric.** Realized loss per decision in the engine's own step-table
currency, scored against grounded outcomes:

- For decision a ∈ {ask, block, proceed} on a call whose grounded label is
  decisive (accepted ∪ reverted), the realized loss is the negated
  step-table entry `−u[a][state]` with **state = wanted for accepted,
  wasteful for reverted** (`membrane.utility_rows`: block-on-accepted = λc,
  proceed-on-reverted = c, ask = q in either state; a measured `spend_usd`
  substitutes for c in the proceed-on-reverted cell when present).
- The headline is the mean over decisive records; a two-sided bound extends
  the mean over all grounding-backed records with ambiguous scored both
  ways (the ambiguous bucket can weaken confidence but never silently
  vanish, and cannot be gamed in either direction).
- Decision-agreement-% stays retired (it measures conformity to the
  incumbent, not quality); `membrane_diff` remains a shadow sanity check
  only (its current reading and staleness: `docs/membrane-shadow.md` §4).

**The grounding.** Labels come from the structural session classifier
(`training/outcomes.py`): reverted = an explicit undo of the same target
within 12 calls (high-precision); accepted = executed and the session
continued; everything else ambiguous. Shadow mode makes every grounded
outcome the realized proceed-world counterfactual for all three decisions.

**The corpus definition.** The bench (`benchmarks/outcome_bench/`) scores a
snapshot of `observations.jsonl` pinned by manifest {path, n_lines,
sha256, read_at}; every artifact embeds its manifest and intersections are
warned, never silent. The registered reading's manifest is recorded in the
committed `outcome_bench_results.json` at registration time.

## 2. The exit-from-shadow bar (values for the author to declare)

Enforcement was turned off because the incumbent blocked too often. It
returns **per category**, only when an engine's false-block rate on
grounded outcomes clears a declared bar with a minimum-evidence floor:

    clears(k) ⇔ FBR_k ≤ bar_k  ∧  n_accepted_k ≥ n_min

where FBR_k = (blocks landing on accepted) / (accepted calls in category
k). The SHAPE ships in `bench.clears_bar`; the values are the author's:

| category | bar_k (FBR ≤) | n_min | declared window |
|---|---|---|---|
| waste    | ☐             | ☐     | ☐               |
| safety   | ☐             | ☐     | ☐               |

Context for the choice (measured, 2026-07-10 reading): the incumbent's
FBR and per-category tables are in `benchmarks/outcome_bench/OUTCOME_BENCH.md`;
its catch-on-reverted is 0 (zero outcome-justified blocks in ~15k decisive
records), so its break-even wasteful base-rate is π* = ∞ — blocking that
never catches waste never pays at any base rate.

## 3. What closes R-D14 and what does not

Closes: the author signing (a) this metric as the membrane's registered
acceptance standard, (b) the bar values + window above, at a proplang
freeze boundary. From that signature the membrane's field performance is
measurable by a registered standard and the interregnum line on the
register closes.

Does NOT close: any promotion decision (Phase 4 — meets-or-beats on this
metric over a declared shadow window, the `run()` backend-selection change,
and any harm-channel admission are separate author acts), the A gate
(Phase 3), and the latent@1 `said`-degeneracy question (the live shadow's
ask-rate reading is the falsification instrument; a stake-bearing `said`
form is proplang-side growth only the author can open —
`docs/membrane-shadow.md` §0).

## 4. Caveats carried into the registration (verbatim from the bench)

The register entry should carry the bench's caveats register
(`OUTCOME_BENCH.md`, items 1–10) — in particular: ambiguous handling
(bounds, never dropped), the label-recovery caveat (accepted-but-errored →
ambiguous), category recomputed with today's rule, profile assumed default
(not persisted), ask scored flat −q pending real ask verdicts, and π*'s
closed form.
