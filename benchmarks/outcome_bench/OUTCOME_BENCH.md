# The outcome-scored governance bench (Phase 1)

Scores governance decisions against GROUNDED OUTCOMES in the engine's own step-table currency — the R-D14 candidate metric replacing retired decision-agreement-%. Registration of the metric and the bar values is the author's act (`docs/rd14-registration-draft.md`); this page is the measured reading. Regenerate: `bench.py` then `report.py` (see module docstrings).

## Corpus

- snapshot: `/home/g/.credence-governor/observations.jsonl` — 100882 lines, sha256 `b3ec4bb1122a489d…`, read 2026-07-10T19:41:18Z
- joined decisions: **34278** (orphans: {'decisions_without_proposal': 0, 'outcomes_without_proposal': 0, 'proposals_without_decision': 0})
- would-block rate: **18.89%**; decisive records (accepted ∪ reverted): **15165**; reverted: 10; outcome-justified blocks: **0**
- drift note: the log grows live (the daemon keeps deciding); this table supersedes the roadmap's 2026-07-10 baseline — same shape, larger counts.

| decision | accepted | reverted | ambiguous | hook-only | ungrounded | total |
|---|---|---|---|---|---|---|
| ask | 169 | 0 | 137 | 25 | 63 | 394 |
| block | 2570 | 0 | 3102 | 19 | 785 | 6476 |
| proceed | 12416 | 10 | 11133 | 1629 | 2220 | 27408 |

## Engines on the same corpus

| engine | mean loss $/decision | bounds (ambiguous both ways) | FBR (waste) | FBR (safety) | ask-rate on accepted | catch on reverted | π* break-even |
|---|---|---|---|---|---|---|---|
| ORACLE | 0.00000 | [0.00000, 0.24329] | 0.00% | 0.00% | 0.00% | 100.00% | 0.0000 |
| UNGOVERNED | 0.00033 | [0.00017, 0.24346] | 0.00% | 0.00% | 0.00% | 0.00% | 0.0000 |
| incumbent | 0.08529 | [0.04388, 0.28485] | 6.50% | 37.66% | 1.12% | 0.00% | ∞ |
| membrane-table@1 | 0.02000 | [0.02000, 0.02000] | 0.00% | 0.00% | 100.00% | 0.00% | ∞ |

- challenger replay: proplang-govhost `table@1` — 33918 of 34278 decisions scored (replay snapshot sha256 `1fee4277bf624f5b…`; MANIFEST MISMATCH — intersection scoring)

## The exit-from-shadow bar (SHAPE shipped; values UNREGISTERED)

Enforcement returns per-category only when an engine's false-block rate on grounded outcomes clears a declared bar with a minimum evidence floor. The numeric bars are the author's R-D14 registration act; until then every row reads UNREGISTERED.

| category | bar (FBR ≤) | n_min | incumbent clears? |
|---|---|---|---|
| safety | UNREGISTERED | 100 | — |
| waste | UNREGISTERED | 100 | — |

## The caveats register (binding on any reading of the numbers)

1. **Realized-state assignment**: accepted ⇒ the wanted column, reverted ⇒
   the wasteful column of the engine's own step table (`membrane.utility_rows`;
   block-on-accepted = λc, proceed-on-reverted = c, ask = q flat). Reverted is
   the log's only high-precision "unwanted" signal (explicit undo within 12
   calls); acceptance = ran + session continued.
2. **Ambiguous is never dropped silently**: the headline mean is over decisive
   records (accepted ∪ reverted); the two-sided bound scores every
   grounding-backed record with ambiguous counted both ways.
3. **Shadow counterfactuals**: shadow mode means every logged call executed,
   so grounded outcomes are the realized proceed-world for ALL decisions —
   blocks and asks are scored against what actually happened to the call they
   would have stopped.
4. **Label recovery**: the persisted grounding record stores only
   completed/reverted; accepted-but-errored calls land in ambiguous.
   Hook-only events (result-hook `completed=true` is universal in shadow
   mode) are non-decisive.
5. **Ask scoring** is the flat −q step-table row; ask-resolution scoring
   awaits real ask verdicts (asks never actually asked in shadow mode).
6. **Category** is recomputed with TODAY'S `_block_category` rule over the
   logged decide-time features — not necessarily the rule live at decision
   time (not persisted).
7. **Profile** is assumed default for the incumbent's logged decisions (not
   persisted). The profile sweep re-VALUES decisions; it does not re-decide.
8. **retries** is diagnostic-only (single-digit nonzero counts — no
   statistical power); **spend_usd** substitutes for c in the
   proceed-on-reverted cell when measured (inert while unlogged); **error**
   is unused (folded into completed at grounding time); **latency** is
   telemetry (the step table has no time column — deliberately not yet
   priced).
9. **π\*** is the per-decision analogue of the INTEGRATED.md break-even:
   π\* = B / (B + catch·c) with B = FBR·λc + ask-rate·q per wanted decision;
   catch = 0 ⇒ π\* = ∞ (blocking that never catches waste never pays).
10. **The challenger replay** boots on warm counts only and interleaves
    verdicts at their log positions (no future-evidence leak); outcome
    records are not fed (table@1/epoch-1 has no outcome channel). Scored on
    the event_id intersection when the log grew past the replay's snapshot
    (drift is warned, never silent).

## Profile sweep — mean loss $/decision under each buyer profile (presets ∪ personas)

| profile | ORACLE | UNGOVERNED | incumbent | membrane-table@1 |
|---|---|---|---|---|
| balanced | 0.00000 | 0.00033 | 0.08529 | 0.02000 |
| cost-saver | 0.00000 | 0.00033 | 0.02207 | 0.05000 |
| fintech-safety | 0.00000 | 0.00033 | 0.17002 | 0.02000 |
| indie-hacker | 0.00000 | 0.00033 | 0.02174 | 0.02000 |
| quality-first | 0.00000 | 0.00033 | 0.17091 | 0.10000 |
| quality-research | 0.00000 | 0.00033 | 0.17002 | 0.02000 |
| regulated-enterprise | 0.00000 | 0.00033 | 0.17002 | 0.02000 |
| speed-first | 0.00000 | 0.00033 | 0.09064 | 0.50000 |
| startup-balanced | 0.00000 | 0.00033 | 0.08529 | 0.02000 |
