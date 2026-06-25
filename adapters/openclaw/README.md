# credence-openclaw

Bayesian **routing and governance** for OpenClaw. One brain, one utility
function, your cost/quality trade-off.

- **`before_model_resolve`** — EU-max model routing: picks the cheapest
  model whose expected accuracy justifies it, learns from outcomes. On by
  default.
- **`before_tool_call`** — in-loop governance: forwards each proposed tool
  call to the credence-openclaw daemon and maps the decision back to OpenClaw:

| brain effector | OpenClaw result |
|---|---|
| `proceed` | allow |
| `block`   | `{ block: true, blockReason }` |
| `ask`     | `{ requireApproval }` — OpenClaw's native approval dialog; the user's choice is posted back so the brain learns |

It also logs tool **outcomes** (`after_tool_call`) and reconstructs
**per-turn cost** (`llm_output` token counts × a price table) so the
observation log accumulates the data the dollars-saved surface needs.

**Fail-open:** if the daemon is unreachable or slow, the tool proceeds
(one warning per outage). Governance never blocks the agent on
infrastructure failure.

This is the OpenClaw adapter of [credence-governor](https://github.com/gfrmin/credence-governor):
one of several thin bodies over the same brain (the Python `governor_core` daemon,
which talks to the `credence-skin` engine). The Claude Code adapter is its sibling.
The daemon wire (POST `/sensor`, SSE `/signals`) is shared across adapters.

## Why a plugin (not a pi extension)

Current OpenClaw vendors pi's coding-agent and runs its gateway agent with
`noExtensions: true`, so a pi `ExtensionFactory` never loads. The supported
interception point is an OpenClaw **plugin** `before_tool_call` hook.

## Install (operator)

1. Start the **governor daemon** — the Python `credence-governor-core`, which runs the
   one EU-max reasoner over the `credence-skin` engine. It listens on
   `http://127.0.0.1:8787`. Not yet on PyPI, so install from a clone of the repo:
   ```bash
   pip install -e packages/governor_core -e ~/git/credence/apps/skin/clients/python
   CREDENCE_SKIN_COMMAND="docker run --rm -i ghcr.io/gfrmin/credence-skin@sha256:<digest>" \
     credence-governor-daemon
   ```
   (or, against a local engine checkout, `CREDENCE_ENGINE_DIR=/path/to/credence
   credence-governor-daemon`). See [`packages/governor_core`](../../packages/governor_core).
2. Build the plugin: `cd adapters/openclaw && npm install && npm run build`.
3. Install it into OpenClaw by linking this checkout:
   `openclaw plugins install -l adapters/openclaw` (once it's on npm:
   `openclaw plugins install @gfrmin/credence-openclaw`).
   Then `openclaw plugins enable credence-openclaw`.
4. **Per-turn cost signal.** On current OpenClaw (≥ 2026.6.2) the `llm_output`
   cost hook is active out of the box — no extra config. (Older builds gated it
   behind a since-removed `plugins.entries.credence-openclaw.hooks.allowConversationAccess`
   flag; that key is now rejected by the config schema.) Governance —
   allow/block/ask — never depended on it.
5. Restart the gateway so it picks up the plugin.
6. Verify it loaded: `openclaw plugins list` shows `credence-openclaw` as `loaded`.

## Config (`openclaw.plugin.json` → `configSchema`)

| key | default | meaning |
|---|---|---|
| `daemonUrl` | `http://127.0.0.1:8787` | credence-openclaw daemon base URL |
| `hookTimeoutMs` | `3000` | max wait for the daemon decision before failing open |
| `approvalTimeoutMs` | `120000` | how long OpenClaw waits for the user on an `ask` before denying |
| `redactToolInputs` | `false` | omit tool-call inputs from sensor events (they can carry secrets); ask-preview becomes generic |
| `shadowMode` | `false` | observe-only: brain decides + daemon logs, body never enforces or overrides the model |
| `routing` | `true` | EU-max **model routing** via `before_model_resolve` — ON by default, roster-aware (see below); set `false` to disable |
| `silent` | `false` | suppress info/warn logs |
| `pricing` | — | per-model USD/Mtok overrides: `{ "<model>": { "input": n, "output": n, "cacheRead": n, "cacheWrite": n } }` |
| `profile` | `"balanced"` | your cost/quality trade-off preset: `cost-saver`, `balanced`, `quality-first`, `speed-first` — sent to the daemon per request, switch any time |
| `profileOverride` | — | advanced: override individual utility dials on top of the preset — keys: `reward`, `lambda`, `q`, `harm`, `w_time`; any subset |

**Privacy:** by default the daemon logs `proposed_call.input` (commands, paths) to
`~/.credence-openclaw/observations.jsonl`. Set `redactToolInputs: true` to keep inputs out of the log.
Fail-open warnings are emitted once per outage (re-armed when the daemon recovers).

The built-in price table is approximate; set `pricing` for an exact
dollars-saved figure for your providers. Unknown/unpriced models log
`usd: null` (token counts still recorded; the Move-2 surface applies a
token×price fallback).

## Model routing (on by default, roster-aware)

The plugin registers a `before_model_resolve` hook that routes each turn to the
EU-max model. It discovers the models OpenClaw actually has — from `api.config`
(the configured providers, their models, and per-Mtok pricing) — posts a
`route-request` carrying that **live roster** plus the prompt's length feature,
and applies the brain's chosen model as OpenClaw's `modelOverride` /
`providerOverride`. The decision is the **same EU-max** the governor runs —
`argmax_a [ value·P(correct|X) − cost_a ]` over the live roster, through the one
canonical `optimise` — so credence-openclaw picks the cheapest model whose expected
accuracy justifies it under the active profile.

| brain effector | OpenClaw result |
|---|---|
| `route` | `{ modelOverride, providerOverride }` from the chosen model |
| (timeout / daemon down / <2 priceable models / undiscoverable roster) | no override — OpenClaw keeps its configured model (fail open) |

**On by default; safe by construction.** Routing is enabled unless you set
`routing: false`. The hook registers only when the plugin discovers **≥2
priceable models** to choose between, so a single-model install (or one whose
models can't be priced) is a silent no-op that keeps OpenClaw's model. With equal
cold priors the EU-max reduces to the **cheapest** model, then learns to escalate
to a pricier one only where it earns its cost — cost-saving from day one, never
mis-routing to a hardcoded default. `shadowMode: true` logs the would-route per
turn without changing the model.

**The per-profile dial** lives in `bdsl/utility.bdsl` (`correct-answer-value`: low
⇒ cost-sensitive, high ⇒ quality-sensitive). The shipped `bdsl/routing.bdsl`
declares a default haiku/sonnet/opus roster used only as a fallback when a request
carries no live roster (an older body); the live roster from `api.config` is what
routing actually uses.

**What the belief is.** Each model's accuracy belief `P(correct | X)` is its own
structure-BMA. Models matching the shipped warm seed
(`brain/routing_brain.counts.json`, distilled from a 3-frontier-model oracle grid)
are **calibrated from install**; the user's **own** models start from a weak prior
and **learn online** — each routed turn's per-turn outcome (did the proposed call
execute cleanly, `tool-completed.success`?) updates the routed model's belief. That
signal is noisy (a correct call can fail on a flaky tool), so the brain models the
confound explicitly and learns it (per-context tool-reliability): a flaky tool is
absorbed by the reliability latent, not blamed on the model. Updates go through the
canonical `condition` (mean-exact, so routing's EU is exact); a human
approve/reject is the gold anchor. Per-call **cost** comes from the user's config
pricing (output-$/Mtok × a shared per-call token scale; a learned per-model
`E[tokens/call]` is a follow-up). Honest limits — per-turn proxy ≠ ground-truth
correctness; false-success is weakly identified; run-level credit assignment is
deferred — are in `eval/results/ROUTING_DOMINANCE.md`. The belief is durable
(route-outcomes are logged and replayed on restart). Routing currently conditions
on `prompt-length` (the one feature honestly extractable from a raw prompt); the
structure-BMA collapses it to the marginal if it doesn't predict accuracy. Richer
covariates are a follow-up.

## Develop

```
npm install
npm run build      # tsc → dist/
npm run typecheck  # tsc --noEmit
npm test           # node --test (tsx) over tests/*.test.ts
```

## Architecture (server-side extraction)

Feature & taint extraction is **server-side**, single-sourced in the governor core
(`packages/governor_core`, Python). This adapter carries **no** feature or safety
logic: `session.ts` maintains a per-run **message buffer** (tool calls + results) and
posts the harness-neutral `{tool_name, input, session:{cwd, project_root, messages}}`;
the daemon extracts. This is the same neutral shape the Claude Code adapter builds from
its transcript — one extractor, every harness (DRY). Routing's `prompt-length` feature
is the one exception that stays client-side (it has no cross-harness analogue).

## Known limitations (Move 1 / MVP-0)

- `working-directory-relative` and `time-since-last-user-message` are best-effort
  (OpenClaw doesn't put a cwd or message timestamps on the tool ctx — cwd is mapped
  from the tool's first derived path, and there is no user-message hook to stamp);
  the loop-relevant features (tool-name, parent, repetition) are exact.
- `redactToolInputs` blanks the tool input in the human-facing **ask-text preview**
  and keeps it out of the observation log (which stores only derived feature buckets);
  the real input still reaches the local daemon transiently for extraction (you cannot
  detect identical-call loops without seeing the args).
- Cost USD is reconstructed from a local price table (no host `calculateCost`
  dependency); override via `pricing`.
- The per-run message buffer is bounded per run but the run map is not evicted on a
  long-lived gateway — a cleanup item.
