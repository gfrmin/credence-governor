# Approach-dominance MVP benchmark — design doc

*Supersedes `tokenshift-comparison-DESIGN.md`. Follows `docs/posture-3/DESIGN-DOC-TEMPLATE.md` (7-section structure). This is a **truth-finding** artifact, not a persuasion one: its job is to map where Credence wins, ties, and loses across the scenario space and **classify every loss**, not to manufacture a winning number. §3 and §4 are adapted from the template's refactor framing ("behaviour preserved / dispatch trace") to "integrity invariants / worked findings". Reviewers reject this doc if §5 is boilerplate or if the loss-triage (§App-D) is treated as optional.*

---

## 1. Purpose

**The MVP claim under test:** *Credence beats every other approach across a wide range of scenarios and utility profiles, on the individual axes and decisively once trade-offs are priced in — for 1–3 harnesses — and where it does not, we know exactly which cell, by how much, and why.*

The success criterion is **not** "Credence dominates everywhere." A benchmark that dominates everywhere is the benchmark a rigged bench produces, and nobody credible believes it. The deliverable is a **complete, classified win/tie/loss map**: for every (scenario × profile × harness) cell, who wins and by how much, and for every *loss* cell a classification into one of three causes — **capability-gap**, **calibration-deficit**, or **benchmark-artifact** (§App-D). Losses are findings, not failures: a capability-gap loss is a product backlog item, a calibration loss is a flywheel claim (show the curve), an artifact loss is a bench fix. The MVP is done when the map is complete and every loss is triaged — *that* is the product roadmap falling out of the benchmark.

**Beat the class, not the competitor.** Enumerating competitors is a losing game (the next funded launch invalidates the list). Instead we dominate the **idealised upper bound of each competitor class**, so "but competitor X is better than you modelled" stops being a valid objection:
- *Routing class* — already covered by `baselines.py`: `make_best_fixed_table` (the strongest profile-agnostic static router, the Wald foil), `make_threshold_router` (RouteLLM-style), and `make_oracle_cascade` (FrugalGPT-style, **clairvoyant** — a strict upper bound on any real cascade). Beating the cascade beats every shipping router.
- *Compression class* — a parameterised **synthetic upper-bound** arm (§App-A): the best a compressor could plausibly be (idealised cut, zero quality loss, perfect policy). TokenShift is one *named, real point inside this class*, steelmanned from its published claims.
- *Static-guard class* — a perfect-allow-list policy: the upper bound on static governance.

This is what licenses "beats all other approaches" honestly: not a competitor roll-call, but dominance of the *frontier of what any single-lever approach could achieve*. The prediction the architecture makes (§4) is that Credence's one irreducible loss region is exactly the lever it cannot yet pull — compression on harm-indifferent, routing-headroom-free workloads — and naming that gap precisely is a *better* MVP result than a clean sweep. That is the architectural *prediction*; empirically the region turns out to be **empty on the measured grid** (no headroom-free cell occurs in three real models — routing always has somewhere to go), so the boundary must be *synthesised* to be characterised at all, and stacking closes it even there. "The gap is hard to even produce" is the honest, and stronger, framing — see §5.2 and §App-C-7.

What unblocks: the loss map *is* the prioritised product backlog; the win magnitudes *are* the marketing numbers; the triage *is* the difference between building levers you need and chasing artifacts you don't.

**Decided repo boundary (rules §2; closes the old §5.1).** The engine (`credence`) owns *language capability demonstrations* — "`optimise` can express routing", asserted on a toy grid, with no competitor, profile, or dollar in it. The governor (`credence-governor`) owns *every evaluation that asserts a product or competitive claim* — all the arms, profiles, personas, the loss map, the triage — and reaches the engine the same way the daemon does at runtime: as a dependency over the skin client / the published `credence-skin` image, not as a source-level import of engine internals. The principle in one line: **anything with a competitor, a profile, or a dollar in it is the governor's; the engine stays domain-blind.** This makes the repo split *enact* the company thesis (a general engine, one application on top) rather than merely assert it.

## 2. Files touched

The repo boundary is **decided** (see §1): the engine owns a capability smoke test only; the governor owns the entire competitive evaluation and calls the engine as a runtime dependency. This means the bulk of the work — including the routing arm, which today lives in the engine's `routing_dominance` — is born in or moves to the governor.

**Engine repo (`credence`) — keep a capability smoke test only (strip the competitive parts):**
- `apps/python/credence_router/experiments/routing_dominance/` — **slim to a capability demonstration.** What stays: a minimal "routing via `optimise` beats fixed single-model choices on the toy oracle grid" example proving the *primitive* works. What leaves (moves to the governor): the synthetic/TokenShift/stacked arms, the profile sweep, the personas, the win/tie/loss verdicts, the dollar accounting — everything asserting a product or competitive claim. If slimming the existing experiment is messier than starting clean, the cleaner path is to leave `routing_dominance` as a self-contained internal demo and **birth the competitive eval fresh in the governor**; recommend that unless the grep (§6) shows the experiment is already cleanly separable.
- Net: the engine gains nothing coding-agent-specific and asserts only language properties. *This is the point of the move — the engine is provably domain-blind because there is not one competitor fact in it.*

**Governor repo (`credence-governor`) — hosts the full approach-dominance eval; depends on the engine via the skin wire:**
- `benchmarks/approach_dominance/` — **new dir** (the artifact home; all of the below live here).
- `benchmarks/approach_dominance/routing_belief.py` — **new.** Builds the models×categories Beta-Bernoulli routing belief through the **skin client** (adapted from the engine's `routing_state.py` — it's a small `build_state` + the router preference dict), conditions on the oracle grid, and calls `skin.optimise` for the EU-max routing decision. Depends on the engine the same way the daemon does at runtime (the `credence-skin` image / skin client) — **not** a source import of `credence_router` internals. *The probability arithmetic stays in the engine; this file only declares structure and calls Tier-1 primitives.*
- `benchmarks/approach_dominance/arms.py` — **new.** All competitor arms (moved here because each encodes a competitive claim): the promoted router foils (`best_fixed_table` Wald foil, `threshold_router` RouteLLM-style, `oracle_cascade` clairvoyant upper bound), `make_synthetic(cost_mult, quality_delta, harm_coverage)` (the single-lever upper-bound family), `make_tokenshift(...)` (a named instance of the compression class), `make_stacked(profile)` (Credence routed ∘ modelled compression — the only place "Credence pulls compression" appears, **modelled**, §App-D). Every arm maps a question to a realised `(correct, cost)` against the shared frozen grid.
- `benchmarks/approach_dominance/fixtures/oracle_grid.json` — **new (vendored from the engine).** The frozen *measured* fixture travels with the eval that consumes it, because it is product-evaluation data, not language data (`models: [cheap, mid, exp]`; per model×question correctness + cost). The n-caveat travels with this file.
- `benchmarks/approach_dominance/scenarios.py` — **new.** Scenario generator (§5.2): emits the set varying routing-headroom, category mix, difficulty, attack density — so "wide range of scenarios" is explicit, not a single grid.
- `benchmarks/approach_dominance/dominance.py` — **new.** Runs every (arm × profile × scenario), emits `(cost, quality, latency)` and the per-cell win/tie/loss verdict vs each competitor → `routing_results.json`.
- `benchmarks/approach_dominance/synthetic_competitors.py` — **new.** The competitor-class config block (§App-A): synthetic upper bounds, the TokenShift instance, the perfect-policy guard — every parameter most-favourable-to-competitor, in one place.
- `benchmarks/approach_dominance/harm_compare.py` — **new.** Runs the governor injection corpus through (i) Credence taint-flow via `training/cand_eval.py` `Metrics` and (ii) the static-policy upper bound → `harm_results.json`.
- `benchmarks/approach_dominance/aggregate.py` — **new.** Consumes both JSONs; per-axis tables, the EU sensitivity surface over (λ, harm), the persona table, the dominance fraction over the realistic region, **the win/tie/loss map** → `SUMMARY.md`, `LOSS_MAP.md`.
- `benchmarks/approach_dominance/loss_triage.py` — **new. The centerpiece.** Per loss cell, the three diagnostics (§App-D) → `cause ∈ {capability-gap, calibration, artifact}` + evidence. A loss with no cause is a hard error.
- `benchmarks/approach_dominance/harness_matrix.py` — **new.** Per harness in scope (§5.5), which axes are live: OpenClaw = routing + governance; Claude Code = governance (routing N/A until the harness exposes model choice); harness-neutral core = the oracle-grid routing. Keeps the "1–3 harnesses" claim honest about *what* each harness measures.
- `benchmarks/approach_dominance/tests/test_approach_dominance.py` — **new.** Sanity/structure assertions only (§3).
- `benchmarks/approach_dominance/README.md` — **new.** Measured-vs-modelled ledger; re-run instructions; how to read `LOSS_MAP.md`.

Reused as-is: `training/{cand_eval.py,corpus.py,red_team.py,fp_eval.py}`; `adapters/openclaw/src/profile.ts` (presets/dials, mirrored to Python — §5.4); the engine via the skin client / `credence-skin` image (a **runtime** dependency, the same one the product has — not a source dependency). The operational tax (the eval needs the engine available to run) is accepted deliberately: it is the product's own dependency shape, so the eval sharing it is honest rather than convenient.

## 3. Integrity invariants + assertion classes  *(adapts "Behaviour preserved")*

The harness is honest iff these hold; each is a test (§7). **Note the inversion: dominance is a *finding*, not an assertion.** The tests assert the bench is *sound*, not that Credence *wins*.

- **Findings, not pass/fail on dominance.** A loss cell does **not** fail the suite. It fails **only if untriaged** (no `cause` assigned) — an unexplained loss is the one intolerable state. *Assertion: every loss cell in `LOSS_MAP.md` carries a `cause` and its diagnostic evidence.*
- **Measured-vs-modelled tagging (per cell, propagated).** Every output **cell** tags `source ∈ {measured, modelled}`. Routing cost/quality from the oracle grid = measured; anything downstream of a synthetic/TokenShift/policy assumption = modelled; the stacked arm = measured-routing × modelled-compression (tagged as such). Tags **propagate to every aggregate** (each derived number carries its measured/synthetic cell counts), and the **headline dominance number is computed over the measured-cell subset** (§5.2-G1, §7). *Assertion: no untagged cell; every aggregate carries its (measured, synthetic) counts; the headline is measured-subset-only.*
- **Upper-bound, not strawman.** Every synthetic competitor sits at the *most favourable to the competitor* end of its declared range (best plausible compressor, perfect policy). A `--competitor-best-case` run pushes them further and is part of the cadence. *Assertion: synthetic params are at the favourable bound; the best-case run's loss map is pasted into the README.*
- **Same ground truth across arms.** All arms map to outcomes against the same frozen oracle grid / same corpus. *Assertion: one grid object, one corpus, shared by all arms.*
- **No hardcoded thresholds.** Verdicts are structural: `win` iff strictly cheaper at ≥ quality (or higher harm-recall at ≤ fire-rate); `tie` within a declared epsilon band; else `loss`. The epsilon is a declared parameter, not a magic constant. *Assertion classes:* `verdict ∈ {win,tie,loss}` computed structurally; `harm_recall(credence) >= harm_recall(policy)` on the allowed-channel subset (the one place a strict win is expected by construction); `cost(stacked) <= min(cost(credence), cost(tokenshift))` at equal quality.
- **n caveat carried.** Task/scenario counts printed next to every number with the cluster-bootstrap note.

## 4. Worked end-to-end example  *(one win cell and one loss cell, traced — the loss cell is the point)*

Balanced profile (`reward=1.0, λ=1.0, q=0.02, harm=1.0, w_time=0.014`). *(Illustrative numbers shaped like the grid; implementation reads real values.)*

**A win cell (routing has headroom).** Category `c`, where `cheap` is correct at \$0.004 and `exp` is correct at \$0.026. Credence routes to `cheap` → `(correct, $0.004)`. TokenShift-on-exp (compression) → `$0.0224`; TokenShift-on-cheap → `$0.0034`. Synthetic best-compressor on cheap (30% cut) → `$0.0028`. **Verdict vs synthetic-best:** Credence $0.004 vs $0.0028 — a *loss on raw cost* at this cell. **Stacked** (route cheap, then compress) → `$0.0028` — *ties* the synthetic bound. So even the "win" region surfaces a cost-only loss to an idealised compressor that stacking neutralises. This is the architecture's prediction visible in one cell.

**A loss cell (no routing headroom — the irreducible case).** A category where *only* `exp` is ever correct (`cheap`/`mid` wrong). Credence's EU-max correctly routes to `exp` (anything else fails the task) → `(correct, $0.026)`. The synthetic best-compressor on `exp` → `$0.0182` (30% cut, same correct outcome by assumption). **Verdict: Credence loses this cell on cost, by ~30%, and routing cannot help because there is no cheaper correct model.** → **Triage (§App-D):** diagnostic 1 (stacked recovery) — does Credence∘compression recover it? Stacked on `exp` → `$0.0182`, *ties* the bound. So the loss is classified **capability-gap (compression)**: the cell is lost *only* because Credence can't pull the compression lever it would pull if it shipped it; the stacked arm proves the lever closes it. **Backlog consequence:** "ship compression; the same EU-max will choose it here." Not a calibration issue (belief is irrelevant — the routing decision is forced), not an artifact (the scenario is realistic: hard tasks where only the strong model succeeds).

This is the MVP working as intended: the loss is real, bounded, explained, and converted into one roadmap line.

## 5. Open design questions

1. **Cross-repo home — RESOLVED (see §1 decision, §2 layout).** The engine keeps a capability smoke test; the governor hosts the full eval and calls the engine via the skin client. Left here only as a pointer so the numbering of the genuinely-open questions below is stable. The one residual call for the reviewer: confirm whether to *slim* the engine's `routing_dominance` or leave it as an internal demo and birth the eval fresh in the governor (§2 recommends the latter pending the §6 grep).
2. **Scenario range — RESOLVED (measured-anchored hybrid).** The single oracle grid is one scenario; the claim needs a *generated* set varying routing-headroom, category mix, difficulty, and attack density. The fork (real-but-narrow vs synthetic-but-wide) resolves to a **hybrid governed by an evidential-burden asymmetry**: the headline claim and the boundary finding carry different burdens, so they may meet different standards *provided each cell is labelled with the standard it meets*. The marquee dominance claim is a *positive* claim (we ask the reader to believe it) → **measured**. The no-headroom loss is a claim *against our own interest* (we surface a weakness) → a synthetic-but-clearly-tagged scenario is fully credible, because no one rigs a bench to invent their own losses. So: **measured where we claim strength, synthetic-but-tagged where we admit weakness.** Concretely: a measured anchor + measured resamples on category-mix and difficulty; a synthetic headroom knob turned *only* where the real grid cannot reach (~18 scenarios + anchor). Three guardrails keep the hybrid from rotting into synthetic-but-wide:
   - **(G1) Per-cell tags that propagate.** `source ∈ {measured, modelled}` is tagged **per cell, not per run**, and every derived number (dominance fraction, EU surface, persona table) carries "computed over M measured + K synthetic cells." The **headline dominance number must be computable over the measured subset alone and is reported that way first** (§7 enforces this — the hard-fail checks the *headline*, not that some measured row merely exists).
   - **(G2) Synthetic confined to the headroom axis.** The synthetic knob exists solely to populate the no-headroom cell. It must **not** leak into the category-mix or difficulty resamples, which stay measured. Synthesising difficulty/correctness "to widen coverage" is the drift into synthetic-but-wide and is a review stop.
   - **(G3) Synthetic cells adversarial by construction.** The headroom is dialled to the *competitor's* advantage (max compression gain, min routing headroom), never a neutral midpoint — the cell's job is to be Credence's worst realistic case. A softer dial flatters rather than characterises the boundary.

   **Meta-finding to surface (not engineer around):** a clean no-headroom cell *does not occur in three real models on MCQs* — routing always has somewhere to go — so the predicted irreducible-loss region is **empty on measured data**. The benchmark states this directly (§App-C-7): the boundary must be *manufactured* to be shown, and stacking closes it even there. That the gap is hard to even produce is a *stronger* result than a found loss.
3. **Realistic-region prior** (§App-B) — declared, swappable, excludes only the harm-indifferent corner. Uniform vs persona-weighted?
4. **Profile source of truth** — mirror `profile.ts` to Python with a drift-guard test, or read it?
5. **Harness scope for "1–3 harnesses."** The routing comparison is harness-neutral (oracle grid) and the harm comparison is harness-neutral (corpus); the *harness-specific* part is integration overhead and which axes are live per harness (OpenClaw routes; Claude Code governs only). So does "1–3 harnesses" mean (i) run the harness-neutral comparison and *report* per-harness which axes apply (cheap, honest, recommended), or (ii) actually drive each harness in-the-loop and measure real overhead (expensive, and adds little to the dominance claim)? If (ii), which 1–3 and why?
6. **Triage thresholds** (§App-D). The calibration diagnostic re-runs a loss cell with a warmed belief — how much warming is fair before "calibration" becomes "we tuned until we won"? Propose a fixed, declared conditioning budget (e.g. the belief warmed only on *other* scenarios' data, never the test cell's) so calibration-recovery can't cheat.

## 6. Risk + mitigation

- **Triage that rationalises (the credibility-killer for a truth-finding bench).** *Failure:* every loss gets explained away as "calibration" or "artifact" so the capability-gap list stays empty and flattering. *Blast radius:* the whole MVP — an empty backlog from a benchmark that should produce one is the tell of a rigged triage. *Mitigation:* the three diagnostics are *mechanical and falsifiable* (§App-D), not judgement calls; the calibration diagnostic has a fixed conditioning budget (§5.6) that forbids fitting the test cell; capability-gap is the **default** cause when stacked-recovery succeeds and calibration fails, so the harness is biased *toward* finding real gaps, not away. A run that reports zero capability-gaps is itself flagged for manual review.
- **Strawman / over-modelled competitor** → synthetic params at the favourable bound; `--competitor-best-case` cadence run; perfect-policy as the guard upper bound.
- **Self-graded aggregate** → per-axis un-weighted table is the substance; aggregate ships only as a sensitivity surface with the full grid and the named TokenShift-winning corner exposed.
- **Compression over-claim** → "Credence pulls compression" appears *only* as the stacked arm, tagged measured×modelled; **no** Credence-native-compression arm exists; the capability-gap triage explicitly names compression as unbuilt. The roadmap narrative, not a measured result.
- **Scenario degeneracy mistaken for loss** → the artifact diagnostic (§App-D) checks routing-headroom per cell; a cell where one model strictly dominates is annotated `artifact: no-headroom`, not counted as a competitive loss.
- **Grep-and-disposition (pre-code):** the grep now serves the *move*, not an in-place extend — for each hit decide port-to-governor / leave-as-engine-demo / reuse-via-skin. `grep -rn "make_always\|make_oracle_cascade\|make_best_fixed_table\|_router_preference\|build_state" apps/python/credence_router` (the arms + belief-construction the governor's `arms.py`/`routing_belief.py` must reproduce by calling skin primitives — copy the *structure*, not a source import of engine internals); `grep -rn "harm_recall\|class Metrics" packages/governor_core` (harm surface, reused in place); `grep -rn "PRESETS\|resolveProfile" adapters/openclaw/src` (dials → Python). Confirm the engine's `routing_dominance` is cleanly separable so the slim-vs-rebirth call (§2, §5.1) can be made.

## 7. Verification cadence

The eval interpreter is `uv run --project packages/governor_core` (binds local source);
the engine is reached via `build_skin_client()` (`CREDENCE_ENGINE_DIR` dev checkout or the
published image), the daemon's own runtime path.

```
# engine — capability smoke test only (proves the primitive; asserts nothing competitive)
uv run --project apps/python/credence_router --with pytest \
  python -m pytest apps/python/credence_router/experiments/routing_dominance -q

# governor — the entire approach-dominance eval, with the engine available as a dependency
export CREDENCE_ENGINE_DIR=/path/to/credence            # or CREDENCE_SKIN_COMMAND for the image
R="uv run --project packages/governor_core python benchmarks/approach_dominance"
uv run --project packages/governor_core --with pytest python -m pytest benchmarks/approach_dominance/tests -q
$R/dominance.py            # routing belief via skin -> routing_results.json (headline asserted measured)
$R/harm_compare.py         # -> harm_results.json
$R/loss_triage.py          # -> every loss gets a cause (skin: warmed-belief calibration)
$R/aggregate.py            # consumes all three -> SUMMARY.md, LOSS_MAP.md
$R/dominance.py --competitor-best-case  &&  $R/loss_triage.py  &&  $R/aggregate.py   # the steelman re-run
```
(loss_triage precedes aggregate — aggregate consumes the triage. The steelman re-runs the
*dominance* step with a deeper compressor, then re-triages and re-aggregates.)
Halt-the-line: any test failure; **any loss cell without a triage `cause`**; any output **cell** missing its `source` tag; **the eval silently degrading to modelled because the engine wasn't reachable**. The measured-source assertion is on the **headline**, not on the existence of some measured row: the dominance step asserts that the **headline dominance number is computed over the measured-cell subset** (`routing_results.json.headline.source == "measured"` and its `measured_cell_count` matches the cells the headline integrates) and hard-fails otherwise — so a synthetic cell can never silently enter the marquee claim. A dominance *loss* does **not** halt — it is the expected output.

---

## Appendix A — competitor classes (single block, upper-bounded, steelmanned)

```python
# synthetic_competitors.py — every assumption most-favourable-to-competitor, in one place.

# Compression class — the BEST a compressor could plausibly be (an upper bound on the class):
SYNTH_COMPRESSOR = dict(cost_mult=0.70, quality_delta=0.0, harm_coverage="policy_only")  # 30% cut, no quality loss
# TokenShift — a NAMED, REAL point inside the compression class (its published claims, steelmanned):
TOKENSHIFT = dict(compression=0.20, input_frac=0.70, quality_delta=0.0, latency_delta=0.0, routing=False)

# Static-guard class — perfect allow-list (upper bound on static governance):
PERFECT_POLICY = dict(allowlist="generous")   # caught iff allow-list violation; allowed-channel attacks => miss (structural)

# Routing class — already in baselines.py, promoted to named competitors:
#   make_best_fixed_table (Wald foil) · make_threshold_router (RouteLLM-style) · make_oracle_cascade (FrugalGPT, clairvoyant UB)

# Credence's only compression access is the STACKED arm: route (measured) then apply compression (modelled). Tagged.
# There is NO Credence-native-compression arm. Compression is an unbuilt lever (capability-gap, by design).
```

## Appendix B — personas + realistic region

| Persona | reward | λ | harm | w_time | stands for |
|---|---|---|---|---|---|
| Indie hacker | 0.02 | 0.25 | 0.25 | 0.002 | cost-precious, harm-indifferent (≈ the degenerate corner) |
| Startup / balanced | 1.0 | 1.0 | 1.0 | 0.014 | the median business |
| Regulated enterprise | 2.0 | 2.0 | 2.5 | 0.014 | balanced + harm-averse |
| Fintech / safety-critical | 5.0 | 2.0 | 3.0 | 0.014 | harm dominates |
| Quality research team | 5.0 | 2.0 | 2.0 | 0.014 | pays for the best |

**Realistic region** (prior the dominance fraction integrates over): `harm ∈ [0.5,3.0] × λ ∈ [0.25,4.0]`, uniform, **excluding** `harm < 0.25`. Declared, swappable, printed.

## Appendix C — findings catalogue (the sentence each result licenses — wins AND losses)

Only assert a sentence if its test/triage is green.
1. **Class dominance:** "Credence's frontier weakly dominates the routing class (incl. a clairvoyant cascade — an upper bound on any real router) across all profiles." *(measured, N tasks.)*
2. **Per-profile margin:** "For the {profile} user, Credence is X% cheaper at equal task-success than the best {class} operating point." *(per-axis, un-weighted.)*
3. **Harm gap:** "Static policy catches P% (allow-list only); Credence taint-flow catches R%. The gap is the allowed-channel class policy is structurally blind to." *(strict win on the allowed-channel subset.)*
4. **Stacked complementarity:** "Stacked, Credence∘compression ≤ either alone at equal quality." *(measured×modelled; assumes compression preserves correctness — the competitor's own claim.)*
5. **Dominance fraction:** "Over the realistic region (harm ≥ 0.5), Credence dominates F% of the weighting space." *(prior declared.)*
6. **The honest boundary (a LOSS, stated as a finding):** "On harm-indifferent, routing-headroom-free workloads, an idealised compressor beats Credence on cost by up to G% — a capability-gap (compression, unbuilt); the stacked arm shows the lever closes it. This is the one cell we lose, and the plan to win it." *(this sentence is the MVP's most credible output.)*
7. **The empty boundary (the measured meta-finding):** "On the real oracle grid, *no* routing-headroom-free cell occurs — every category has a cheaper-and-correct model somewhere, so the predicted irreducible-loss region is **empty on measured data**. To characterise the boundary at all we must *synthesise* one adversarially-dialled no-headroom cell (tagged modelled), and even there the stacked arm closes it. The compression gap is therefore so marginal we had to manufacture the conditions for it to bite — a stronger, more honest boundary statement than a loss found in the wild." *(measured: the absence of the cell; modelled: the synthesised cell, tagged. Frames §App-C-6 rather than replacing it.)*

## Appendix D — loss triage protocol (the centerpiece)

Every loss cell is classified by three **mechanical** diagnostics, run in order. The first that fires assigns the cause.

1. **Artifact check (run first — cheapest, and stops false signals).** Is the cell degenerate? Compute routing-headroom: is there a cheaper model that is *also* correct on this cell? If **no** (one model strictly dominates → routing is worthless *by construction*), or if the competitor's modelled params exceed their declared favourable bound, or if the quality metric is ill-defined here → `cause = artifact` (annotate, exclude from the competitive count). *Not a product signal.*
2. **Capability-gap check.** Does the **stacked** arm (Credence ∘ the lever the competitor pulled) recover the cell — i.e. Credence-alone loses but Credence∘lever wins or ties? If **yes** → `cause = capability-gap`, naming the lever (today: compression). *This is the backlog: build the lever; the EU-max already knows when to pull it.*
3. **Calibration check (run last; fixed conditioning budget — §5.6).** Re-run the cell with the belief warmed **only on other scenarios' data** (never this cell's outcome). Does the gap close? If **yes** → `cause = calibration`. *This is a flywheel claim: emit the per-session convergence curve — a deterministic competitor cannot draw it.*

If none fire, the cause is `capability-gap (unknown lever)` **by default** — the bias is deliberately *toward* admitting a real gap, never toward explaining one away. A loss that reaches this default is flagged for manual review. A run reporting **zero** capability-gaps is itself flagged: a truth-finding bench that finds no gaps has almost certainly mis-triaged.
