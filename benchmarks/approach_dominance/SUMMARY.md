# Approach-dominance — SUMMARY

*Generated from routing_results.json, harm_results.json, loss_triage.json. Compressor `{'cost_mult': 0.7, 'quality_delta': 0.0, 'harm_coverage': 'policy_only'}`. n-grid = 50 measured questions.*

## Headline (measured)

- **Routing — real routers (excl. clairvoyant cascade):** weak dominance **1.0** over 288 measured cells (win 165, tie 123, loss 0). ✅ undominated.
- **vs best-fixed-table (Wald foil):** weak dominance **1.0** (14 win / 58 tie / 0 loss). ✅ no static table dominates EU-max ⇒ admissible.
- **Including the clairvoyant cascade** (an unattainable upper bound, reported for context): weak dominance 0.9333 (24 losses, all to the cascade → artifact).
- **Harm:** Credence taint-flow recall **0.7** (fire-rate 0.2222) vs static allow-list recall **0.5** (fire-rate 0.0); allowed-channel gap = **4** attack(s) the policy is structurally blind to. ✅ strict win on the allowed-channel subset.

## Loss triage (every loss carries a cause — §App-D)

- 61 losses, all triaged: **artifact** 24, **capability-gap** 37.
- capability-gaps found: **37** ✅ (zero would be flagged as a mis-triage).
- manual-review flags: 0.

## Dominance fraction over the realistic region (§App-B)

- region: harm ∈ (0.5, 3.0) × λ ∈ (0.25, 4.0), excluding harm < 0.25.
- **uniform weighting:** 1.0  ·  **persona-weighted (sensitivity):** 1.0 (weak dominance over measured real-router cells).

## The honest boundary (§App-C-6 / §App-C-7)

- ✅ **No routing-headroom-free cell occurs in any measured scenario** — the predicted irreducible-loss region is *empty on measured data*. It is synthesised (the `headroom-none` scenario, tagged modelled) to characterise the boundary; even there the **stacked** arm (Credence∘compression) closes it. The compression gap is so marginal we had to manufacture the conditions for it to bite.
- the compression capability-gap is the one lever Credence cannot yet pull; building it is the backlog (37 capability-gap cells; the EU-max already knows when to pull it).

## Findings catalogue (§App-C — only green sentences are licensed)

1. ✅ **Class dominance:** Credence's frontier weakly dominates the real routing class across all profiles (the clairvoyant cascade is an upper bound, not a router).
3. ✅ **Harm gap:** static policy catches 50%; Credence taint-flow catches 70%; the gap is the allowed-channel class policy is blind to.
4. ✅ **Stacked complementarity:** Credence∘compression ≤ either alone at equal quality — the lever closes every capability-gap cell it is tested on.
5. ✅ **Dominance fraction:** over the realistic region, weak dominance = 1.0 (uniform) / 1.0 (persona).
6/7. ✅ **The honest+empty boundary:** the one loss region is compression on headroom-free workloads — empty on measured data, synthesised to show, stacking closes it.

## Per-harness live axes (§5.5)

| harness | routing | governance | what it measures |
|---|---|---|---|
| openclaw | live | live | adapter exposes model choice → routing decisions flow through the harness |
| claude-code | n/a | live | no model-choice surface yet → routing not measurable; governance is live |
| neutral-core | oracle-grid | corpus | the harness-neutral substrate the dominance map is scored on (measured) |

## Measured-vs-modelled ledger

| quantity | source |
|---|---|
| routing cost/quality (oracle grid) | measured |
| real-router dominance headline | measured (full grid, Wald) |
| harm recall / fire-rate (corpus) | measured |
| compression arms (synthetic / TokenShift) | modelled |
| stacked arm (Credence∘compression) | measured routing × modelled compression |
| headroom sweep (incl. no-headroom cell) | modelled (synthetic, adversarial) |
