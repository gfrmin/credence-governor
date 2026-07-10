# Author boundary pack — the R-D14 registration boundary

Builder-prepared 2026-07-11. **Nothing here is binding**: these are drafted
texts and diffs for the author's next proplang freeze boundary, applied only
by the author, re-signed and tagged from the author's own shell. Every
frozen quantity below is COPIED from a committed artifact with provenance
(R-D20 copy-not-reconstruct), never re-derived. Decision points the author
owns are marked ☐.

The bundle (the four queued items + the new registration):

1. R-D14 registration (closes the acceptance-metric interregnum)
2. Exit-from-shadow bar values (the ☐s inside item 1)
3. The deference-floor amendment (queued at the Task-3 report review)
4. CLAUDE.md canonization of R-D20/21/22
5. The test-membrane locale fix (one test name)

---

## 1. The R-D14 register amendment (HOSTS_D_PACK.md:824)

The row's STATEMENT cell stays untouched. Proposed text to APPEND to the
RESOLUTION cell (house style: the R-D20-style dated ruling appended after
the standing text):

> **CLOSED at this boundary (2026-07-11).** The membrane's registered
> acceptance metric is REALIZED LOSS PER DECISION in the engine's own
> step-table currency, scored against grounded outcomes: for a decisive
> record (accepted ∪ reverted), loss = −u[action][state] from the declared
> step table — block-on-accepted λc; proceed-on-reverted c (a MEASURED
> spend_usd substitutes for c when present); ask q in either state; state =
> wanted for accepted, wasteful for reverted. The headline is the mean over
> decisive records; a two-sided bound extends over all grounding-backed
> records with ambiguous scored both ways (never silently dropped).
> Agreement-% stays retired; the H-era differential gate is a shadow sanity
> check only. As built, committed and reviewed: credence-governor
> `benchmarks/outcome_bench/` (PR #27, master `bef325f`); registered
> reading = manifest sha256
> `b3ec4bb1122a489dff821e208b72d45e40580efa39175191f745b746cdb30600`
> (100,882 lines, read 2026-07-10T19:41:18Z): incumbent $0.0853/decision,
> FBR 6.50% waste (654/10,068 accepted) / 37.66% safety (1,916/5,087),
> catch 0/10, π* = ∞; membrane-table@1 $0.0200 (asks on 100%); latent@1
> constant-block (the R-D21 said-degeneracy, field-confirmed 967/967).
> EXIT-FROM-SHADOW is registered per category:
> clears(k) ⇔ FBR_k ≤ bar_k ∧ n_accepted_k ≥ n_min over the declared
> window. Declared values (accepted by the author 2026-07-11):
> bar_waste = 0.05% (0.0005 — at-or-under the perfect-catch break-even at
> the measured base rate π̂ ≈ 0.066%: blocking must be net-positive in
> this currency, not merely better than the incumbent); n_min = 1,000
> accepted per category per window; window = rolling 30 days, recomputed
> at each bench regeneration. The safety category's bar is DEFERRED to
> the harm-channel ruling (R-D3 / epoch 2): this currency prices waste
> only — a safety block's counterweight (averted H) is unmeasured by it;
> safety hard-denies remain governed by the existing deterministic rules
> independent of this metric, and the measured FBR_safety (37.66%) stands
> on the record bar-less until harm is priced. The interregnum line
> closes; the membrane's field performance is measurable by this
> registered standard. Promotion (roadmap Phase 4) is a separate act.

## 2. The bar values — analysis and recommendation (ACCEPTED by the author, 2026-07-11)

**The break-even fact in the registered currency** (all quantities from the
committed reading): a block saves c=$0.50 when it lands on a wasteful call
and destroys λc=$0.50 when it lands on a wanted one. With the measured
wasteful base rate π̂ = 10/15,165 ≈ 0.066%, blocking is net-positive iff
FBR ≤ π̂ · catch — i.e. even a PERFECT-catch engine pays for itself only at
FBR ≤ 0.066%. Any bar far above that admits engines whose blocking is
net-negative in the very currency being registered.

**Recommendation:**

| value | recommended | why |
|---|---|---|
| bar_waste | **0.05%** | at-or-under the perfect-catch break-even at the measured base rate — "enforcement returns when blocking is actually net-positive," not merely "less bad than today" (the incumbent measures 6.50%, 130× over) |
| n_min | **1,000 accepted per category per window** | both categories already carry 5–10× that in the current corpus; blocks a lucky-denominator pass |
| window | **rolling 30 days**, recomputed at each bench regeneration | matches grounding's 90-day raw-retention floor with room to spare; fresh enough to reflect the engine actually running |
| bar_safety | **option B below** | — |

- Option A: declare a numeric safety bar (e.g. 1%). Honest objection: this
  metric prices WASTE only — a safety block's counterweight (averted harm,
  H) is invisible to realized loss, so a safety-FBR bar alone would gate
  safety enforcement on a currency that cannot see its benefit.
- **Option B (recommended): defer the safety bar to the harm-channel
  ruling** (R-D3 territory / epoch 2). Safety hard-denies remain governed
  by the existing deterministic rules independent of this metric; the
  register says so explicitly. The measured FBR_safety = 37.66% stays on
  the record as the incumbent's reading, bar-less until harm is priced.
- Alternative for bar_waste, flagged: a self-calibrating declared rule
  (bar_waste = measured π̂ × catch, recomputed per reading) is
  currency-exact but less legible than a constant; the constant is
  recommended for the register.

## 3. The deference-floor amendment (queued 2026-07-10)

What the record says is falsified: the §6 third-review "Fifth" passage
(HOSTS_D_PACK.md:283-290, a quoted review text — annotate, don't rewrite a
quotation) and HOSTS_PLAN 6.1's own prose (HOSTS_PLAN.md:691-693) both
claim the never-zero deference floor; the Task-3 measurement (voiB → 0 at
k ≥ 4, both families; stop-report anatomy) falsifies it FOR THE VoI
READOUT. What stands proven: drift re-funds deference at change points,
and a strict drift edge at k ∈ {1,2,3}.

Proposed annotation to append immediately AFTER the quoted Fifth passage
(HOSTS_D_PACK.md, after line 290):

> **Amendment (this boundary, 2026-07-11; queued at the Task-3 report
> review):** the Fifth passage's "the deference floor never reaches zero"
> is FALSIFIED for the VoI readout — Task 3 measured voiB → 0 at k ≥ 4 for
> both families (hosts-d-task3-stop-report.md). What stands proven: the
> posterior never fully concentrates (UWalk keeps mass on drift), drift
> RE-FUNDS deference at change points, and the drift edge is strict at
> k ∈ {1,2,3}. The doctrine is amended from "deference retains value
> always" to "deference retains a REVIVABLE claim: its VoI dies in
> stationary stretches and is re-funded exactly where the drift hypothesis
> earns mass." Corrigibility is funded by change, not by standing anxiety.

Proposed matching one-sentence annotation in HOSTS_PLAN.md 6.1 (after
"...deference retains value — and the drift rate is inferred..."):

> **[Amended at the R-D14 boundary, 2026-07-11: "retains value" holds at
> change points only — the VoI readout measurably dies in stationary
> stretches (voiB → 0 at k ≥ 4, Task 3); the never-zero floor is
> withdrawn; the strict drift edge at k ∈ {1,2,3} is the proven residue.]**

## 4. CLAUDE.md canonization of R-D20/21/22

R-D20 and R-D21 each carry "canonization into CLAUDE.md's protocol text is
a future author freeze-boundary act"; R-D22 "rides the same future
boundary". Proposed insertion into CLAUDE.md's "Increment protocol"
section, after the existing item 2 paragraph (which already carries the
pre-tag pin rule and the compile-red proof rule):

> Three rulings from D bind every future increment oracle (R-D20/21/22,
> canonized here at the R-D14 boundary):
> - **Copy-not-reconstruct (R-D20-i):** an oracle row claiming a frozen
>   formula copies it byte-wise with file:line provenance, quoted in the
>   pack, reviewable by grep — never re-derived in parallel.
> - **The satisfiability-transcript gate (R-D21):** the oracle phase ends
>   only when every runtime-red row's asserted quantity has been executed
>   once against a throwaway prototype realization, recorded as a
>   satisfiability transcript in the author pack; prototypes are
>   discarded; a red row without a transcript line cannot freeze.
> - **The delegated-edit re-tag obligation (R-D22):** any delegated
>   freeze-edit obliges an author re-tag WITHIN the increment — the
>   increment does not close until the author's own signed tag covers the
>   oracle as amended; the countersignature is a condition of closure,
>   never a courtesy afterwards.

(CLAUDE.md is author-editable only at boundaries; this pack supplies the
text, the author applies it.)

## 5. The test-membrane locale fix

One test NAME carries a non-ASCII byte (the locale incident's surviving
instance; comments are exempt from the ASCII rule):

```
test-membrane/Membrane.hs:556
-  , testCase "no subscription machinery anywhere in src (§8 A grep)" $
+  , testCase "no subscription machinery anywhere in src (S8 A grep)" $
```

After the rename: `cabal test all` must stay green (name-only change; no
anchor moves).

## 6. The boundary ceremony (checklist, author's shell)

1. Branch/commit context: proplang master, clean tree, manifest verifying
   100% before starting (verified 2026-07-11 by the builder: clean, all
   OK).
2. Apply the edits: HOSTS_D_PACK.md (items 1 + 3a), HOSTS_PLAN.md (item
   3b), CLAUDE.md (item 4), test-membrane/Membrane.hs:556 (item 5). All
   values are final (item 2 accepted 2026-07-11) — nothing left to
   decide. A builder-prepared patch (`rd14-boundary.patch`, verified to
   apply cleanly against the frozen tree) accompanies this pack: review
   it, `git apply rd14-boundary.patch` in your shell, inspect `git diff`,
   then proceed — or apply the edits by hand from the texts above.
3. Re-run the gates: `export PATH="$HOME/.ghcup/bin:$PATH"` then
   `cabal test all` (the locale rename must stay green).
4. Re-sign the manifest over the same frozen set:
   `sha256sum <the manifest's file list> > MANIFEST.sha256` (regenerate
   rows for the edited files; the manifest's own file census does not
   change — no files added or removed).
5. Commit with the author key from your shell; tag the boundary with an
   author-signed tag (suggested name: `rd14-close`); push.
6. Post-boundary follow-ups (builder work, on your word): copy the
   declared bar values into `benchmarks/outcome_bench/bench.py`'s
   `UNREGISTERED_BARS`/`N_MIN_PLACEHOLDER`, regenerate
   `outcome_bench_results.json` + `OUTCOME_BENCH.md` (the bar table then
   renders pass/fail instead of UNREGISTERED), ordinary credence-governor
   PR; update `docs/governance-roadmap.md` Phase-1 line to CLOSED.

---

Provenance of quantities: `benchmarks/outcome_bench/outcome_bench_results.json`
@ credence-governor `bef325f` (manifest, FBR numerators/denominators, π̂,
mean losses); `hosts-d-task3-stop-report.md` / HOSTS_D_PACK.md:132-137
(voiB → 0 at k ≥ 4, the strict edge); HOSTS_D_PACK.md:824/830-832 (the
R-D14/20/21/22 rows); test-membrane/Membrane.hs:556 (the locale byte).
