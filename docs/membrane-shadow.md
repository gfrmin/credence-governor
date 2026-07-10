# The membrane shadow — host declaration register (Phase 2)

Status: as-built, 2026-07-10 (branch `feat/latent-shadow`). This is the
question→resolution→why register for every host-declared value and rule the
Phase-2 shadow fixes (governance-roadmap.md Phase 2). Everything here is
credence-governor-side DATA or transport; nothing binds the frozen proplang
repository. The author reviews this register; items marked **FLAG** are the
ones where a defensible alternative existed and the author may re-decide.

Conformance sources (frozen, read-only): `membrane-wire.md` §6, the gWire
goldens in `test-d/D.hs`, `host-governor/WireU.hs`, `hosts-d-task3-report.md`
§2a/§5, `hosts-d-task3-stop-report-2.md` §1.

## 0. The stated field prediction (read first)

The wire's implemented `said` subset is exactly `["var",0]` and `["var",1]`
(`WireU.hs` `pSaid`; richer forms error — "ordinary implementation growth
under the frozen wire section, never silent"). The frozen record
(stop-report-2 §1) establishes that `upSaid = Var (S Z)` — wire `["var",1]` —
is **action-degenerate**: information about ū cannot change any decision (all
terminal values move together). In the frozen chooser (`uChoose`), ties keep
the first-listed option and `theta_ask` charges only `ask`; with the R1 menu
`[ask, block, proceed]`, ask strictly loses its θ-charge and block beats the
tied proceed by listing order.

**Stated prediction, on the record before the field run: the latent@1 shadow
fires `block` on every tick; its ask-rate is exactly 0** — regardless of
evidence. Confirmed pre-field against the real d-close binary (the env-gated
integration test pins the latent decide `== "block"`).

Consequence, not blocker: the latent@1 shadow is the wire-v2 **falsification
instrument** (its live ask-rate reading confirms/falsifies both this and the
§2a prior), while the **table@1 co-shadow is the non-degenerate challenger
policy** the Phase-1 outcome bench scores. If the field run does NOT show
constant block, the reading of the frozen driver above is wrong somewhere —
equally a result, surfaced immediately by `training/shadow_report.py`. A
stake-bearing `said` form (the test-d fixture's `If (Call IsEq …)` shape) is
NOT wire-expressible today; growing `pSaid` is proplang-side work that only
the author can open — Phase-3 material, now with a measured demand shape.

## 1. The latent@1 declaration (`membrane.latent_utility_decl`)

```json
{"form": "latent@1", "said": ["var", 1],
 "residuals": [{"name": "theta_ask", "grid": [0.02, 0.05, 0.1, 0.2, 0.4]}],
 "tau": {"points": [0.5, 1, 2], "weights": [0.5, 0.3, 0.2]},
 "price": "tick-price", "gauge": {"zero": "status-quo", "scale": "usd"}}
```

1. **said → `["var",1]`.** Q: which payload? A: the USay environment is
   `(action-code, ū)`; `["var",1]` ("utility = the learned pointer latent")
   is the only coherent wire-expressible sentence — `["var",0]` (utility =
   the action id number) is nonsense. Degeneracy consequence in §0.
2. **residuals → `theta_ask` only, first position.** The driver name-keys the
   charge on the first residual (`theta_` + option name); `theta_ask` must be
   first. **`theta_bad` (declared in the d-close golden) is dropped**: the
   governor menu has no option named "bad" and no comparison affordance
   exists in Phase 2, so it would have neither a measured-unit route nor a
   comparison route — exactly the KSV non-identifiability caveat
   (task3-report §3). Declaring an unconditionable latent is dead weight.
3. **theta_ask grid `[0.02, 0.05, 0.1, 0.2, 0.4]`.** Floor = the governor's
   own declared interrupt cost (`UTILITY["interrupt_cost"]`, sourced
   programmatically — a config change is a visible declaration change under
   the pin test); ceiling = the golden's. Positive by R-D8. **FLAG:** the
   golden's floor was 0.05; including 0.02 commits that asks may be as cheap
   as the incumbent priced them.
4. **tau `{[0.5,1,2], [0.5,0.3,0.2]}` — adopted verbatim from the d-close
   golden.** No measured governor-side owner-noise source exists. Declared,
   never updated (R-D9). **FLAG** for author confirmation.
5. **price → `"tick-price"`, deliberately dormant.** The name is required;
   `upPrice` reads the named feature per tick and absent reads 0. No measured
   per-tick deliberation price exists at decide time, and sending
   `UTILITY["cost"]` would smuggle a declared constant into the measured-price
   slot (the stratification rule: measured cost as world data, never a
   declared constant). **FLAG:** dormant until a measured source exists.
6. **gauge `{status-quo, usd}`.** Outcomes are dollar-denominated
   (`spend_usd`); proceed-with-no-consequence anchors 0. Parsed and required
   by the wire; ignored by the frozen `buildWorldU` — a declaration for the
   record.
7. **menu — unchanged `[ask(3), block(2), proceed(1)]`, R1 order, no
   `compare` affordance.** Menus beyond {ask, block, proceed} are the
   increment-A demand gate (Phase 3). **FLAG:** under the degenerate payload
   the menu order fully determines the fired action; we keep R1 anyway —
   reordering to engineer an outcome would be adapter-side steering.
8. **profiles are table@1-only.** The v2 tick parser drops unknown tick keys;
   latent decide sends `{"features","menu"}` only; the `profile` argument is
   accepted and unused (documented in `decide`'s docstring).

## 2. Stream-tagged evidence (one host rule, live and warm alike)

9. **The verdict double-feed.** One human verdict (from `/feedback` or the
   SSE user-responded path) emits TWO ticks at the same `t`, advancing once:
   an untagged tick (world report role — `P(approve|X)` keeps learning, v1
   continuity) then a `stream:"verdict"` tick (owner-response role — the
   pointer through τ). The two ticks move disjoint agents (world vs utility;
   additive census), so nothing is double-counted within one agent. **FLAG:**
   the single-role alternative (verdict → pointer only; the world unfed, p1
   riding the warm prior) is doctrinally arguable; the author picks. The warm
   corpus is double-fed identically (item 11).
10. **The outcome good-bit** (`log._outcome_good_bit`, waste-only): evidence
    `0` iff `reverted is True`; `1` iff `completed is True and not reverted`;
    **skip otherwise** — ambiguous is not evidence, mirroring the bench's
    ambiguous-bucket exclusion. Polarity: `upOutcome` is a Bernoulli(ū)
    emission and ū is the utility pointer, so 1 = "kept/completed — worth
    paying for". At most ONE outcome tick per event_id (a session-held
    seen-set spanning boot replay and live submits). Per-event
    representative record: source precedence `grounding > openclaw >
    result-hook` (grounding sees session continuation; a shadow-mode
    result-hook's `completed=true` is universal and carries no acceptance
    information), last record within the winning source. **FLAG:**
    `completed=False` without revert evidence is excluded rather than
    counted 0. Evidence ticks re-send the judged event's ORIGINAL
    decide-time features (wire §3); events whose features cannot be joined
    are skipped.
11. **Warm segmentation is DECLARED, never tuned (R-D23):** the fixed warm
    corpus (`warm_brain.counts.json`) collapses to `observe_counts` pairs —
    per context in file order, one untagged line then one `"verdict"` line,
    same `t`, the clock advancing by the context's evidence mass (n1+n0).
    Everything else — the observation log's verdict history, its outcome
    history, and all live traffic — replays per-tick. Boot order: warm
    collapse, then log verdicts in arrival order, then log outcomes in
    arrival order (the two-segment declaration; exchangeable families are
    order-free, the hmm clock reads it as the declared flattening
    approximation). Note the consequence: a latent shadow boot on today's
    log (~30k outcome ticks × ~8 ms) takes minutes in the worker thread,
    growing with the log — the primary is unaffected (the shadow queue
    absorbs; ~1000-slot bound vs ~0.35 decisions/s).

## 3. Transport and observability

12. **Readouts + latency are logged, never branched on.** The v2 decision
    reply's `residual_mean`/`sensitivity` (and v1's `p1`/`entropy_bits`) are
    observability-only (wire §6.4). `MembraneSession.decide` stays a pure
    choice-relay — the scalars land in `last_readouts` and the shadow's
    record writer copies them onto the `membrane-shadow` record; no adapter
    code path reads them (test-pinned: two replies differing only in
    readouts yield the identical action). HOSTS_PLAN 8.12(b) forbids
    host-side decision FORKING — control flow, not observation; an
    append-only telemetry record nothing replays is what those fields exist
    for. Latency is recorded so "latency-viable at hook speed" is measured,
    not asserted.
13. **The membrane-shadow record** (one per shadow decide per form):
    `{event_type:"membrane-shadow", in_response_to, utility_form, action,
    latency_ms, readouts}`. Replay-inert by construction (every
    `log.replay_*` filters by event_type).
14. **Shadow transport knobs** (queue 1024, ≤3 respawns, 60 s backoff) are
    adapter TRANSPORT knobs (HOSTS_PLAN 2.5 class) — they shape delivery,
    never a decision. Failure posture: a dead form drops its items (counted)
    until respawn; respawn budget exhausted = dead until daemon restart; the
    primary path is structurally unreachable from any of it (enqueue-only,
    never-raise submits + a worker-owned session + defense-in-depth
    try/except at every daemon mirror site). Observed in the field: a
    RESPAWN boot blocks the single worker's drain loop (the queue backs up
    for BOTH forms during a table@1 re-boot and drains afterwards; near the
    ~1000-item bound, drops). Accepted single-worker posture — per-form
    workers would trade it for cross-form ordering complexity; revisit only
    if measured drops matter.
15. **Boot vs live double-feed:** `MembraneShadow.start()` snapshots the log
    synchronously before the HTTP server serves; sessions boot against the
    frozen snapshot; everything later arrives only via submits. Events
    arriving while a form awaits respawn are lost for that form (telemetry).
16. **Selection:** `CREDENCE_MEMBRANE_COMMAND` (absence = disabled = zero
    behavior change); `CREDENCE_MEMBRANE_UTILITY` comma-separated forms,
    default `latent@1`, field deploy `table@1,latent@1` (the dual shadow).
    An unknown form fails loudly at construction, before serving.
17. **Epoch-1 scope:** harm never reaches the shadow (`harm_observation` is
    not forwarded; `observe_harm` is inert), routing stays on the Julia
    engine, and `BrainSession` remains the unconditional primary — backend
    selection is Phase 4(b), the author's.

## 4. The membrane_diff sanity-check reading (2026-07-10, for the author)

Running the H-era differential gate today reads **agreement 21/29 = 0.724 —
below its 0.95 threshold (exit 1)**. Verified pre-existing and
branch-neutral: cold (warm-cap 0) runs on master and on this branch produce
byte-identical output, and the warm (full 39k-tick replay) reading matches
the cold one exactly. The gate was last green at the H freeze on the pre-M
corpus; every disagreement is an M1/M2 coding-threat addition
(supply-chain / ci-infra / backdoor-logic red-team cases, plus three M1
benign coding cases), all in the same direction: **julia=proceed,
membrane=ask**. The waste-only Julia path proceeds on attack-shaped cases
(its harm overlay, not compared by this waste-only gate, is what catches
them); the membrane's myopic VOI crosses the ask threshold on those
contexts. Roadmap Phase 2 already demoted agreement-% to a shadow sanity
check (R-D14); whether the 0.95 threshold or the gate's exit-code role
should change is the author's ruling, not tuned here.

Operational notes, measured (2026-07-10 field deploy): on the governor's
3,977-model world a v1 WORLD evidence tick costs ~75 ms (the frozen 8.26 ms
benchmark was the toy 1,241-model world), so the table@1 shadow's 39k-row
warm replay boots in ~49 min — worker-thread time only; decides arriving
before a form is alive are lost for that form (counted posture). The
latent@1 shadow, by contrast, booted in SECONDS: outcome and verdict-pointer
ticks condition only the small utility agents, not the world enumeration —
the log's ~15.7k decisive outcome replays are cheap. Measured live latent
decide latency: p50 4.4 ms. Crash injection verified in the field: killing
the govhost mid-boot left the primary /decide at ~170 ms full-featured,
journal shows dead + respawn 1/3 in 60 s.

## 5. Deployment provenance

The binary is a copied build artifact of the frozen proplang repo:
`install -Dm755 <dist-newstyle>/proplang-govhost ~/.local/bin/proplang-govhost`.
At first field deploy: proplang tag `d-close`, sha256
`96ec3de7a59100c8d46d569452af0f379ee6f0e44036f7706e8282af1ffd6c18`
(recorded in `deploy/membrane.conf`; re-record on refresh). Rollback of the
whole shadow = remove the drop-in + restart.
