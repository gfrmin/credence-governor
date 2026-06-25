# credence-governor — Claude Code adapter

A thin **Claude Code** adapter for [credence-governor](../../README.md): a
`PreToolUse` subprocess hook that Bayesian-governs tool calls (`proceed` /
`block` / `ask`) by asking the governor daemon, which runs the one EU-max reasoner
over the Credence engine.

The adapter carries **no probabilistic code and no feature logic**. Its only job is
to translate Claude Code's native hook events into the harness-neutral wire shape and
render the daemon's decision. Feature & taint extraction is server-side in the daemon
(single-sourced — DRY).

## How it works

```
Claude Code  ──PreToolUse JSON on stdin──▶  credence-governor-claude-code (this hook)
                                                  │  transcript_path JSONL → neutral messages
                                                  ▼  POST /decide  (tool, input, session)
                                            governor daemon (credence-governor-core)
                                                  │  server-side feature/taint extraction
                                                  ▼  one EU-max decision over the skin wire
                                            credence-skin engine (Julia)
        ◀──permissionDecision JSON on stdout──────┘
```

- **`transcript.py`** — replays the session transcript (`transcript_path`) into the
  neutral `messages` list the extractors expect (`user` / `assistant` / `tool_call` /
  `tool_result`). The proposed call — already persisted to the transcript before
  `PreToolUse` fires — is excluded so loop counts see priors only. Sidechain
  (subagent) turns are excluded by default.
- **`client.py`** — `POST /decide` (stdlib `urllib`).
- **`effectors.py`** — maps the governor action to a `PreToolUse` decision.
- **`hook.py`** — the entry point (`credence-governor-claude-code`).

## Overlay semantics (the governor never weakens the host)

| governor action | Claude Code decision | effect |
|---|---|---|
| `proceed` | *(nothing emitted)* | defer to Claude Code's own permission rules |
| `block`   | `deny` + reason | refuse regardless of native rules |
| `ask`     | `ask` + reason | force a user prompt even if native rules would auto-allow |

`permissionDecision: "allow"` is **never** emitted — that would bypass Claude Code's
own safety prompts. The governor can only *add* friction, not remove it.

**Fail-open is absolute.** A malformed event, a daemon that is down, a timeout, or any
error prints nothing and exits 0 — the call proceeds through Claude Code's normal
flow. Run with `CREDENCE_GOVERNOR_DEBUG=1` to log decisions/failures to stderr.

## Capability boundary (Claude Code, hook transport)

| Dimension | Supported |
|---|---|
| Waste gating (loops / repetition) | ✅ |
| Safety (taint-flow / exfil / injected imperatives) | ✅ |
| Routing / model selection | ❌ (no model-resolve hook) |
| Cost / dollars-saved | ◑ observe-only |
| Online ask-response learning | ◌ deferred — see below |

v1 gates **`PreToolUse` only**. `PostToolUse` / `UserPromptSubmit` are intentionally
not wired: neither carries a clean approval label, and treating "the call completed"
as belief evidence would be a second learning path (a constitutional violation), not
just a weak one. The warm-trained brain governs; the daemon logs every decision.
Online ask-learning on Claude Code (inferring the user's reply from the next
transcript turn) is an open design question, deferred.

## Install

**1. Start the daemon** — every adapter shares one local daemon; see the
[core README](../../packages/governor_core) or the
[repo quickstart](../../README.md#install). In short, from a clone of the repo:

```bash
pip install -e packages/governor_core -e ~/git/credence/apps/skin/clients/python
CREDENCE_ENGINE_DIR=~/git/credence credence-governor-daemon   # or CREDENCE_SKIN_COMMAND="docker run … credence-skin@<digest>"
```

**2. Install this adapter and register the hook:**

```bash
pip install -e adapters/claude-code        # not yet on PyPI; once published: pip install credence-governor-claude-code
credence-governor-cc-install               # → ~/.claude/settings.json
# or per-project:  credence-governor-cc-install --project   # → ./.claude/settings.json
```

This appends a `PreToolUse` hook (idempotent; existing settings preserved). Remove
with `credence-governor-cc-install --uninstall`. The hook itself has **no runtime
dependencies** (pure stdlib); `credence-governor-core` is needed only for the daemon and
the parity test. The example config is in [`settings.example.json`](settings.example.json).

### Environment

| Variable | Default | Meaning |
|---|---|---|
| `CREDENCE_GOVERNOR_URL` | `http://127.0.0.1:8787` | governor daemon base URL |
| `CREDENCE_GOVERNOR_TIMEOUT` | `5.0` | per-call `/decide` timeout (s); on timeout → fail open |
| `CREDENCE_GOVERNOR_PROFILE` | *(none)* | utility profile passed to the daemon (e.g. `flow-guard`) |
| `CREDENCE_GOVERNOR_DEBUG` | *(off)* | log decisions/failures to stderr |

## Tests

```bash
python -m pytest tests -q
```

Pure-stdlib at runtime; the round-trip parity test (`test_roundtrip.py`) imports
`credence-governor-core` to assert the wire payload deserialises through the daemon's
`event_and_session_from_payload` to the Session the extractors expect — it is skipped
if the core isn't importable.
