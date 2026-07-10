# Data retention policy (R-D16)

Adopted 2026-07-10, resolving proplang HOSTS_D_PACK register item R-D16: "56 GB of
full session transcripts is a retention and hygiene liability independent of any
channel ruling; wants a policy (retention window, truncation, at minimum an
inventory of what the transcripts contain)."

## Inventory: what lives in `~/.credence-governor/`

| File | Contents | Sensitivity | Retention |
|---|---|---|---|
| `raw_events.jsonl` | One record per gated tool call: `event_id`, `tool_name`, the **full tool input** (shell commands, file contents, prompts — strings capped at `CREDENCE_GOVERNOR_CAPTURE_MAXLEN`, currently 2 MB), captured session context, `truncated` flag. This is session-transcript-equivalent material — the liability R-D16 names. | HIGH — raw commands and file contents | 90 days, compressed (see policy) |
| `observations.jsonl` | The evidence log: `tool-proposed` (categorical features only, no raw content), `decision`, `user-responded` (feedback verdicts), `outcome` (completed / latency / spend / reverted / retries — telemetry, replay-inert). | LOW — features and verdicts, no raw content | **Indefinite.** This is the governor's evidence of record; it is small (tens of MB) and every future warm-boot, bench, and grounding run reads it. |
| `raw_events-*.jsonl.zst` | Rotated, zstd-compressed raw capture archives. | HIGH (same as raw) | Pruned past 90 days |
| `pending-results/` | PreToolUse→PostToolUse correlation stash (event_id + timestamp keyed by call fingerprint). | LOW, transient | Self-clearing (popped on PostToolUse) |
| `data-audit/` | Descriptive dossiers from `training/data_audit.py` (aggregates, no labels). | LOW | Keep with observations |

## Policy

1. **Raw capture window: 90 days.** This equals the grounding-backfill window — raw
   capture exists so `training/ground_capture.py` can backfill structural outcomes
   (reverted / retries / completed) for gated calls; past that window a call is
   either grounded (its outcome record lives forever in `observations.jsonl`) or
   permanently ambiguous, and the raw material is pure liability.
2. **Ground before rotate, always.** The rotate unit
   (`credence-governor-rotate.service`) runs `ground_capture` FIRST, then rotates:
   rename (atomic — the daemon opens the capture file per append, so the next write
   recreates it), zstd-compress, prune archives older than the window. Rotation can
   therefore never destroy ungrounded evidence. Weekly timer, `Persistent=true`.
3. **`observations.jsonl` is never rotated or truncated.** Outcome records emitted
   by grounding survive the raw material they were derived from.
4. **Capture stays bounded, not shrunk.** `CREDENCE_GOVERNOR_CAPTURE_MAXLEN` remains
   2,000,000 (a runaway guard). Deliberately NOT lowered: `_cap` marks any record
   with a truncated string `truncated: true`, and the grounding reader
   (`training/outcomes.py:_raw_records`) skips truncated records entirely — so a
   tighter cap silently removes calls from grounding coverage. Growth is bounded by
   the retention window instead of by per-string truncation.
5. **Capture remains opt-in** (`CREDENCE_GOVERNOR_CAPTURE`, off by default in the
   published package); this policy governs the dogfooding deployment where it is on.

## Backlog disposition (2026-07-10)

The accumulated 60 GB backlog (2026-06-25 → 2026-07-10, ~30k gated calls) was
grounded via `ground_capture` (outcome records verified in `observations.jsonl`,
idempotency confirmed), then rotated and zstd-compressed as the first archive under
this policy.
