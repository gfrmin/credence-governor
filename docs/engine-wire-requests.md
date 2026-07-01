# Wire requests from the governor to the Credence engine

Status: **proposal** — a handoff brief for a coding agent working in `~/git/credence`
(the Julia "skin" engine). Nothing here is built. Each request is additive, reuses
machinery that already exists internally, and is sized/prioritised below.

> **What this is.** The `credence-governor` is a pure wire consumer of the Credence
> brain — zero probabilistic code, stdio JSON-RPC over `credence-skin-client`. It has
> been offloaded onto the current wire as far as the current wire allows (the
> `structure_bma`/`structure_observe`/`structure_decide` tier; harm now learns from
> overrides; `compute_cost` is threaded). Four further offloads are blocked not by the
> governor but by the **wire surface**: the brain computes the quantity internally, but no
> skin verb returns or consumes it. This document specifies those four verbs from the
> consumer's side so the engine can expose them. Facts below were read from
> `master` / `exploration-budget/dominance` at the HEAD current on 2026-07-01; re-verify
> `file:line` against your working tree before editing.

---

## The contract (read this first)

Three invariants shape every request. They are the reason the requests take the shapes
they do — please push back if any request appears to break one, because then I've mis-specified it.

1. **Invariant 1 — arithmetic stays engine-side.** The governor never does probability.
   Every request below ships a **scalar or an action across the wire, never a belief
   object.** This is the same principle behind `belief_at_context`
   (`src/structure_bma.jl:252`) being deliberately export-but-not-a-verb: no consumer
   reads a per-context belief across the wire. These requests honour it — the engine still
   performs every integration; the governor receives the *result* (an `expected_repeats`
   folded into a decision, or a single `Float64` expectation for display/calibration).

2. **Wire-only, versioned.** The governor talks to the brain *exclusively* over the skin
   verbs. There is a juliacall path in the repo (`apps/python/credence_router`); it is
   off-limits to this consumer — do **not** route the governor through it. The protocol is
   versioned at `apps/skin/server.jl:721` (`PROTOCOL_VERSION = "1.12"`), MAJOR on breaking
   change / MINOR on additive (`docs/decouple/master-plan.md`). **All four requests are
   additive → one MINOR bump to `1.13`** (new optional coordinate, new read-only verbs).
   No existing verb changes shape. Remember the CI invariant: the header in `protocol.md`
   must equal `PROTOCOL_VERSION`.

3. **Each request reuses existing internal machinery.** None of these ask you to invent
   math. `belief_at_context`, `GeometricTail`, `expect`, `build_function`, and
   `decide_with_voi`'s `expected_repeats`/`compute_cost` parameters all already exist. The
   work is marshalling, plus (Request 4) surfacing accessors that live on a branch.

**Where verbs live.** `SKIN_METHODS` is the registry (`apps/skin/server.jl:727`, 38
verbs); dispatch is a plain `if/elseif` chain on the method name (`:739`), each arm calling
a `handle_<verb>(params)`. Wire tests follow `apps/skin/test_skin.py` (the structure-BMA
roundtrip at `~:1155` is the closest template — build model, `structure_observe`,
`structure_decide`).

---

## Request 1 — a `tail` coordinate on `structure_decide` (DO FIRST: highest value, smallest surface)

**Why.** `decide_with_voi` already accepts `expected_repeats::Float64` (`src/stdlib.jl:232`)
and prices a block as preventing `tf = 1 + expected_repeats` calls. The governor wants that
count to be **the brain's posterior-predictive tail**, not a hand-typed constant (a typed
per-context cost table is exactly the design this project rejects). The brain already knows
how to compute it — `expect(belief, GeometricTail())` is the posterior-predictive expected
number of remaining steps (`src/prevision.jl:210`, closed form `α/(β−1)` at
`src/ontology.jl:692`). The only thing missing is a way to say "compute it from *this*
continuation belief at *this* context and fold it in yourself."

**What already exists.** `handle_structure_decide` (`apps/skin/server.jl:1300`) already
parses an **optional nested `harm` coordinate** (`:1305–1314`): `{model_id, state_id,
features, harm_cost}` → `belief_at_context(hmodel, htop, X)` → passed to `decide_with_voi`
as `harm_belief`. Request 1 is the *same pattern* for a `tail` coordinate — you have a
working template three lines up from where the code goes.

**Proposed wire surface (additive, optional).** A new optional key on the existing
`structure_decide` request:

```jsonc
"tail": {
    "model_id": "<string>",   // handle of a structure_bma continuation model
    "state_id": "<string>",   // handle of that model's belief state
    "features":  { ... }      // the context X at which to read the tail
}
```

Engine behaviour, mirroring the `harm` arm inside the same `try` block:

```julia
# inside handle_structure_decide, alongside the harm-coordinate parse
er = Float64(get(params, "expected_repeats", 0.0))   # existing scalar fallback
if get(params, "tail", nothing) !== nothing
    t      = params["tail"]
    tmodel = get_model(string(t["model_id"]))
    ttop   = get_state(string(t["state_id"]))
    tb     = belief_at_context(tmodel, ttop, _structure_X(tmodel, t["features"]))
    er     = Float64(expect(tb, GeometricTail()))    # posterior-predictive remaining steps
end
# ... decide_with_voi(bx, kernel; ..., expected_repeats = er, ...)
```

**Semantics & edge cases.**
- **Precedence:** if both `tail` and the scalar `expected_repeats` are supplied, `tail`
  wins (the belief-derived value supersedes the literal). Please document this in
  `protocol.md`.
- **β ≤ 1 divergence.** `expect(BetaMeasure, GeometricTail())` errors for β ≤ 1
  (`src/ontology.jl:692`). A continuation posterior built with the project's symmetric
  `Beta(2,2)` prior floor is `Beta(2+n₁, 2+n₀)`, so β ≥ 2 > 1 **by construction** — this
  cannot fire for a well-formed tail brain. But a caller could pass a model with a
  degenerate prior; wrap the compute in the handler's existing `_wrap_inf(...)` idiom so it
  returns a clean JSON-RPC error, not a raw Julia stacktrace.
- **Invariant 1 holds:** the belief never crosses the wire; the governor passes two string
  handles + a feature dict and gets back only `{"action": ...}`.

**Tests.** Extend the structure-BMA roundtrip in `test_skin.py`: build a second
`structure_bma` model as the tail brain, `structure_observe` a lopsided
continue/stop count at a context, then assert `structure_decide` **with** the `tail`
coordinate flips the action toward `block` (higher `tf` ⇒ a block prevents more calls) at a
cost where it would otherwise `proceed` — and that omitting `tail` reproduces today's
behaviour byte-for-byte.

**Acceptance.** `structure_decide` accepts `tail`; with it absent, behaviour is identical
to `1.12`; with it present, `expected_repeats` equals `α/(β−1)` of the tail belief at the
context.

**Governor-side follow-on this unlocks.** The governor already ships an unused
`data/brain/tail_brain.counts.json` (a `structure_bma` continuation posterior over its
governance features). Once this lands it boots that brain via `structure_bma` and passes the
handle on every `decide` — closing the `expected_repeats` question honestly, with no
governor-side `m`.

---

## Request 2 — a `structure_expect` read verb (numeric rationales + calibration)

**Why.** The governor can currently show only *structural* rationales ("blocked because the
egress destination is external and the payload is credential-shaped"). It cannot show the
*number* — `P(unsafe | context)` — because no verb reads a per-context expectation off a
`structure_bma` belief. That number is also what an offline calibration monitor needs (is
the operator's override stream drifting the posterior in a consistent direction?). The brain
computes it internally inside `handle_structure_decide`; it just isn't readable.

**What already exists.** There *is* an `expect` verb (`handle_expect`,
`apps/skin/server.jl:1121`) — but it takes a **raw `state_id` + a `function` spec** and
operates on *any* registered belief. It does **not** take a `(model, state, features)`
context tuple, so it cannot read a `structure_bma` cell-at-context. `build_function`
(same file) already constructs `Identity`, `Projection`, `nested_projection`, `tabular`,
`linear_combination`, `centered_power`, `centered_square`, and `bdsl` functionals.

**Proposed wire surface (new, read-only, additive).**

```jsonc
// verb: "structure_expect"
{
    "model_id": "<string>",
    "state_id": "<string>",
    "features":  { ... },
    "function":  { "type": "identity" }   // any build_function spec
}
// → { "value": <float> }
```

Handler (a two-line composition of things that already exist):

```julia
function handle_structure_expect(params)
    model = get_model(string(params["model_id"]))
    top   = get_state(string(params["state_id"]))
    bx    = belief_at_context(model, top, _structure_X(model, params["features"]))
    f     = build_function(params["function"])
    Dict("value" => Float64(expect(bx, f)))
end
```

Register it in `SKIN_METHODS` and add the `elseif` arm.

**Semantics & the one extra piece.**
- With `Identity`: returns `P(approve | X)` for the waste model, or `P(unsafe | X)` for the
  harm model — the numeric rationale and the calibration signal, immediately.
- With `GeometricTail`: returns the tail `m` — **but** `build_function` does **not** yet
  construct `GeometricTail` (it isn't in the supported list above). If you want `m` readable
  over the wire (as opposed to only *folded in* by Request 1), add a
  `{"type": "geometric_tail"}` case to `build_function` returning `GeometricTail()`. This is
  optional for Request 2's primary purpose (`Identity` covers rationales + calibration) and
  is the only reason to touch `build_function` at all.
- Read-only: no `STATE_REGISTRY` mutation. Invariant 1 holds — a scalar crosses the wire.

**Tests.** In `test_skin.py`: build + `structure_observe` a known count at a context, then
assert `structure_expect` with `Identity` returns the analytic posterior mean within
tolerance; assert an unknown `model_id`/`state_id` yields a clean error.

**Acceptance.** `structure_expect(model, state, features, identity)` returns the same number
the engine uses internally at that context; adding the verb does not perturb any existing
verb.

**Governor-side follow-on.** Numeric `P(unsafe)`/`P(approve)` in every rationale and PreToolUse
message; a committed offline calibration monitor that reads the posterior at held-out
contexts and flags directional drift the online guardrails can't (they bound drift's
rate/magnitude, never its *direction*).

---

## Request 3 — a per-tool-call duration belief (lowest priority; mostly falls out of Request 2)

**Why.** `decide_with_voi` has a time term `w_time · exp_time` (`src/stdlib.jl:232`) that
currently never bites, because the governor has no source for `exp_time` (expected seconds
for *this* tool call). A block that also saves wall-clock should be able to price that.

**What exists — and why it's the wrong quantity.** `LatencyBelief` (`src/routing.jl:20`) is
`Dict{(model_id, ctx_key) → E[time]}`, a **per-model-turn** Gamma
(`Gamma(α0+Σturns, β0+n_obs) × rate`, `:29`). That's model *turn* latency, not per-tool-call
duration, and it's internal to `RoutingState` — **not wire-readable**.

**The honest shape of this request.** Most of it is *not* an engine ask:
- The governor can model tool-call duration as its **own** `structure_bma` belief (it
  already builds/observes/reads `structure_bma`), keyed on the tool-call context, and read
  `E[duration | X]` via **Request 2's `structure_expect` with `Identity`**. No new engine
  machinery beyond Request 2.
- The **one** genuine engine ask is a likelihood mismatch: duration is positive-continuous,
  and `structure_bma` is **Beta-Bernoulli** (`handle_structure_observe` takes a 0/1
  `observation`, `apps/skin/server.jl:1281`). Modelling duration well wants a **Gamma-conjugate** structural
  belief (the machinery exists — `GammaPrevision` is used in `reconstruct_latency_from_data`
  — but there's no `structure_bma`-tier Gamma model, and no verb to build/observe/read one).

**Recommendation.** Defer until the time term is *shown to matter* on real traffic. If it
does, the minimal ask is a Gamma-likelihood sibling of the `structure_bma` trio
(`structure_bma_gamma` / `structure_observe_gamma`) readable via `structure_expect`. Until
then this stays a documented gap, not a build.

**Acceptance (when built).** `w_time · E[duration|X]` measurably shifts `structure_decide`
on a synthetic long-running-tool context, and `E[duration|X]` is wire-readable.

---

## Request 4 — belief-aware autonomous exploration over the wire (the discovery frontier; largest; has a governor-side prerequisite)

**Why.** Requests 1–2 let the governor *use* the brain's beliefs better. Request 4 is
categorically bigger: let the brain **decide its own internal moves** — discover a new
feature, refine a threshold, compress a dead rule — by their value of information, over the
wire. This is the "internal moves" frontier and the largest offload of decision-making.

**What exists (and where).**
- `explore_grammar` (`src/program_space/exploration.jl:273`), `explore_features`
  (`:351`), `compression_exhausted` (`src/program_space/perturbation.jl:394`) — on
  **`master`**, **not** in `SKIN_METHODS`.
- The raw ops `perturb_grammar` (`:398`) / `add_programs` / `condition_and_prune` **are**
  already verbs (in `SKIN_METHODS`, `apps/skin/server.jl:727`).
- The **scalar EU accessors** that would let a selection layer argmax the meta-actions —
  `exploration_voi`, `feature_discovery_voi`, `perturbation_voc` — exist only on branch
  **`exploration-budget/dominance`**, not on `master`, not on the wire.

**Two blockers, in order.**
1. **Engine-side (yours):** land the scalar accessors on `master`, then wire-expose a
   *selection* verb — "rank the internal moves by their scalar EU/VOC and return the winner
   (or apply it)." With the accessors present this is thin marshalling, not missing math.
   A `:gw_*`-inclusive decide surface is the SPEC §9 unified argmax being assembled.
2. **Governor-side (mine, and the larger one):** every function above operates on
   `Grammar` / `AgentState` / **program-space** types. The governor lives on the **tabular
   `structure_bma`** tier. Consuming exploration means migrating the governor's belief tier
   `structure_bma → grammar/program-space` — which touches train==runtime, warm-seeding, and
   the M4 harm constitution. **That migration is its own design pass, not this brief.**

**So this request is a two-sided dependency, not a drop-in.** The concrete, orderable
engine-side asks are: (a) merge the scalar accessors to `master`; (b) expose one
`explore_*`/selection verb operating on a registered program-space state, returning the
chosen meta-action + its scalar EU. Ship (a) first — it's independently useful and unblocks
the design conversation about (b) and the governor migration.

**Acceptance (engine side).** The scalar accessors are on `master` with tests; a
read-only `explore_*` verb returns the argmax meta-action and its scalar value for a
registered program-space state, without applying it (apply can be a second, opt-in verb).

---

## Out of scope — please do **not** change these

- **Feature extraction / the sensor vocabulary.** The app provides sensors; the engine
  never sees raw content. Keep it that way (Invariant 2 — content stays gated; the harm
  model is structural).
- **Utility values, priors, thresholds.** `λ/q/H/w_time`/reward, `Beta(2,2)`, `p_edge` —
  the app holds the *values*; the engine holds the *machinery*. The symmetric prior is a
  deliberate anti-tuning choice; do not "fix" it.
- **`_block_category`.** A P-independent policy *label* (a hard deny is infinite disutility,
  incompatible with a finite `H`, so the engine can't and shouldn't decide it via EU). It
  stays app-side.
- **The juliacall path.** Do not route this consumer through `apps/python/credence_router`.
  Wire only.
- **Existing verb shapes.** All four requests are additive. No `1.12` request or response
  shape should change; the bump is `1.12 → 1.13` (MINOR).

---

## Summary — priority, size, dependency

| # | Request | Size | Depends on | Verb surface | Unlocks (governor) |
|---|---------|------|-----------|--------------|--------------------|
| **1** | `tail` coordinate on `structure_decide` | **S** | — (mirror the `harm` arm) | +1 optional key | belief-derived `expected_repeats`; boot the shipped `tail_brain` |
| **2** | `structure_expect` read verb | **S–M** | — (`build_function` exists; +`geometric_tail` case optional) | +1 read verb | numeric `P(unsafe)` rationales; offline calibration monitor |
| **3** | per-tool-call duration belief | **S engine / M total** | Request 2; a Gamma-tier `structure_bma` | +Gamma trio (if pursued) | the gate's `w_time·exp_time` term bites |
| **4** | exploration/internal-moves over the wire | **L** | accessors→`master`; **governor program-space migration** | +selection verb(s) | brain-driven feature discovery / compression |

**Recommended order:** 1 → 2 → (3 deferred until the time term is shown to matter) → 4
(land the accessors on `master` first; the full loop waits on the governor-side migration).
Requests 1 and 2 are each a few hours and independently shippable; they are the whole of the
near-term offload. Everything after is a design conversation, not a drop-in.
