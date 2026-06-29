# Approach-dominance benchmark

A **truth-finding** benchmark: it maps where Credence wins, ties, and loses across the
scenario × profile space and **classifies every loss**. A dominance *loss* is expected
output, not failure — it fails only if a loss is left untriaged. The deliverable is the
complete classified win/tie/loss map (`LOSS_MAP.md`) and the findings catalogue
(`SUMMARY.md`), not a single flattering number. See `DESIGN.md` for the full rationale.

The governor hosts the entire eval and reaches the engine over the **skin wire** — the
same runtime dependency the daemon has (`build_skin_client()`), never a source import of
`credence_router` internals. The engine keeps only a competitor-free capability smoke test.

## Run it

The eval interpreter is `uv run` from the governor-core project (binds local source); the
engine is reached exactly as in production. Point it at a dev checkout or the published image:

```bash
# dev engine checkout (spins up apps/skin/server.jl):
export CREDENCE_ENGINE_DIR=/home/g/git/credence
# …or the published image:  export CREDENCE_SKIN_COMMAND="docker run --rm -i ghcr.io/gfrmin/credence-skin:latest"

cd <repo-root>
RUN="uv run --project packages/governor_core python benchmarks/approach_dominance"

$RUN/../../benchmarks/approach_dominance/dominance.py   # routing belief via skin → routing_results.json
$RUN/harm_compare.py                                    # corpus harm           → harm_results.json
$RUN/loss_triage.py                                     # every loss gets a cause → loss_triage.json
$RUN/aggregate.py                                       # → SUMMARY.md, LOSS_MAP.md
$RUN/dominance.py --competitor-best-case                # the steelman re-run (deeper compression)

# tests (structure/integrity only — assert the bench is SOUND, not that Credence wins):
uv run --project packages/governor_core --with pytest python -m pytest benchmarks/approach_dominance/tests -q
```

Halt-the-line (any of these is a hard error): a test failure; a loss cell with no `cause`;
an output cell missing its `source` tag; the headline not computed over the measured subset
(`routing_results.json.headline.source != "measured"`) — i.e. the eval silently degraded to
modelled because the engine was unreachable.

## Current result (measured, n=50 grid)

- **Routing — real routers (excl. clairvoyant cascade): weak dominance 1.0** (0 losses over 288
  cells); **vs the best-fixed-table Wald foil: 0 losses** ⇒ EU-max is admissible. The only routing
  losses (24) are to the *clairvoyant* oracle-cascade → `artifact`.
- **Harm:** Credence taint-flow recall 0.70 (fire 0.22) vs static allow-list 0.50 (fire 0.00);
  **allowed-channel gap = 4** attacks the policy is structurally blind to (strict win).
- **Triage:** 61 losses, all classified — 24 `artifact`, 37 `capability-gap` (compression); 0
  unknown/flagged. The capability-gap is the one unbuilt lever (compression); stacked closes it.
- **Meta-finding (§App-C-7):** *no* no-routing-headroom cell occurs in any measured scenario — the
  predicted irreducible-loss region is empty on measured data; it is synthesised (`headroom-none`)
  to characterise the boundary, and stacking closes it even there.
- **Steelman (`--competitor-best-case`, compression pushed 0.70→0.56):** real-router dominance
  unchanged at **1.0** (compression is orthogonal to routing); every loss still triages; the
  compression capability-gap widens 37→39 cells. The marquee claim is robust to the steelman.

## How to read `LOSS_MAP.md`

Every loss carries a mechanical cause (§App-D), grouped by cause:

- **`artifact`** — not a real competitive signal: a loss to the *clairvoyant* oracle-cascade
  (an unattainable upper bound, not a shipping router), or a degenerate no-routing-headroom
  cell. Annotated and excluded from the competitive count.
- **`capability-gap`** — the product backlog: Credence loses because it cannot yet pull a
  lever the competitor pulled (today: **compression**). The **stacked** arm
  (Credence ∘ compression) closing the cell is the proof the lever shuts it — the EU-max
  already knows when to choose it; it just isn't built.
- **`calibration`** — a flywheel claim: the loss closes once the belief is warmed on *other*
  data (never the test cell's own — §5.6). A deterministic competitor cannot draw that curve.

## Measured vs modelled (the ledger)

| quantity | source |
|---|---|
| routing cost/quality (oracle grid) | **measured** |
| real-router dominance headline (full grid, Wald complete-class) | **measured** |
| harm recall / fire-rate (red-team + benign corpora) | **measured** |
| compression arms (synthetic upper bound / TokenShift point) | **modelled** |
| stacked arm (Credence ∘ compression) | measured routing × **modelled** compression |
| headroom sweep incl. the no-headroom cell | **modelled** (synthetic, adversarial — G3) |

The headline integrates the **measured subset only** (G1); synthetic cells can never enter
the marquee claim. The measured grid is `fixtures/oracle_grid.json` (vendored from the
engine; n=50 questions × 3 models × 5 categories — carry the small-n caveat).

## Files

`routing_belief.py` (belief port, skin primitives only) · `arms.py` (foils + compression
wrappers) · `scenarios.py` (the §5.2 hybrid: measured anchor/resamples + synthetic headroom)
· `synthetic_competitors.py` (§App-A upper-bound config) · `dominance.py` (the routing run)
· `harm_compare.py` (taint-flow vs static policy) · `loss_triage.py` (the §App-D centerpiece)
· `aggregate.py` (→ SUMMARY/LOSS_MAP) · `harness_matrix.py` (§5.5 live axes) · `profiles.py`
(the `profile.ts` mirror + personas) · `tests/` (§3 integrity).
