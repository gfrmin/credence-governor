"""corpus.py — public agent-safety corpora → the governor's neutral schema.

Each corpus trajectory is replayed call-by-call: the proposed call becomes an
`AgentToolEvent`, and the `Session` carries every PRIOR message (tool_call +
tool_result), so the SAME `extract_features` / `extract_safety` used at runtime
produce the training features. This is the single-extractor discipline that the
harm brain must be trained under — train == runtime — replacing the forked
`credence_pi_eval/analysis/atbench_taint.py` extractor.

tool_result messages carry `tool_name` = the PRODUCING tool (provenance), read
straight from the corpus (`toolResult.toolName`).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterator

from ..schema import AgentToolEvent, Message, Session


def _msg_text(m: dict[str, Any]) -> str:
    """Flatten a corpus message's content to text (string or list-of-blocks)."""
    c = m.get("content", m.get("text"))
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        out = []
        for b in c:
            out.append(str(b.get("text", "")) if isinstance(b, dict) else str(b))
        return " ".join(out)
    return ""


@dataclass
class LabeledCall:
    """One proposed tool call from a corpus trajectory, with its causal session
    context and the trajectory's safety labels (label is trajectory-level; harm
    attribution to a specific call is done separately, see
    build_harm_brain.localize_harm)."""

    corpus: str
    session_id: str
    idx: int  # 0-based index over the trajectory's tool calls (matches reason-attribution)
    event: AgentToolEvent
    session: Session
    is_safe: bool
    risk_source: str | None
    reason: str


# ── ATBench-Claw (AI45Research/ATBench) ──────────────────────────────────────
# The OpenClaw assistant's declared own-footprint: its identity/config files. Reading
# these is the agent inspecting itself (own-source); every other read may be attacker-
# plantable (a downloaded doc, a shared note). Mirrors the reference extractor's _POLICY
# trusted set; feeds the `source-locality` feature (Invariant 2 declared data).
ATBENCH_TRUSTED_PATHS = [".openclaw", "SOUL.md", "USER.md", "IDENTITI", "IDENTITY"]


def load_atbench(path: str) -> list[dict[str, Any]]:
    """Load an ATBench test.json: a list of {trajectory, labels, reason} records."""
    with open(path) as f:
        return json.load(f)


def _atbench_events(record: dict[str, Any]) -> list[dict[str, Any]]:
    return record.get("trajectory", {}).get("events", [])


def iter_atbench_calls(record: dict[str, Any], session_id: str) -> Iterator[LabeledCall]:
    """Yield one LabeledCall per assistant toolCall, in trajectory order. The
    Session for call N contains all messages strictly BEFORE call N (causal)."""
    labels = record.get("labels", {})
    is_safe = bool(labels.get("is_safe", True))
    risk_source = labels.get("risk_source")
    reason = record.get("reason") or ""
    messages: list[Message] = []
    idx = 0
    for e in _atbench_events(record):
        m = e.get("message", {})
        role = m.get("role")
        if role == "user":
            messages.append(Message(role="user", result=_msg_text(m)))
        elif role == "assistant":
            content = m.get("content")
            blocks = content if isinstance(content, list) else []
            for b in blocks:
                if not (isinstance(b, dict) and b.get("type") == "toolCall"):
                    continue
                name = b.get("name") or ""
                args = b.get("arguments") or {}
                # The proposed call is gated against the session SO FAR (this call
                # is not yet in messages — matching the live PreToolUse contract).
                yield LabeledCall(
                    corpus="atbench-claw",
                    session_id=session_id,
                    idx=idx,
                    event=AgentToolEvent(tool_name=name, input=args),
                    session=Session(messages=list(messages), trusted_paths=ATBENCH_TRUSTED_PATHS),
                    is_safe=is_safe,
                    risk_source=risk_source,
                    reason=reason,
                )
                idx += 1
                messages.append(Message(role="tool_call", tool_name=name, input=args))
        elif role == "toolResult":
            # tool_name = the PRODUCING tool (provenance); result = the consumed content.
            messages.append(
                Message(role="tool_result", tool_name=m.get("toolName"), result=_msg_text(m))
            )


def iter_atbench(path: str) -> Iterator[LabeledCall]:
    """All labeled calls across an ATBench corpus file, session_id = atbench-<n>."""
    for i, record in enumerate(load_atbench(path)):
        sid = record.get("trajectory", {}).get("session_id") or f"atbench-{i}"
        yield from iter_atbench_calls(record, sid)
