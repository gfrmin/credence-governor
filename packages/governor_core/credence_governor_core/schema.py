"""schema.py — the harness-neutral event contract.

Every adapter's job is to translate its harness's native events into these
shapes; the governor extracts features and decides from them. Deliberately
decoupled from any harness runtime so adapters and tests construct them freely.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

MessageRole = Literal["user", "assistant", "tool_call", "tool_result"]


@dataclass
class Message:
    role: MessageRole
    # The tool's name (on tool_call messages).
    tool_name: str | None = None
    # The tool call's arguments (on tool_call messages) — used to count repeats
    # of the SAME call (the argument-level loop signal). Absent on non-tool messages.
    input: Any = None
    # ISO-8601 timestamp; absent on synthetic / pre-existing messages.
    timestamp: str | None = None
    # The tool result content (on tool_result messages) — the taint SOURCE.
    result: Any = None


@dataclass
class AgentToolEvent:
    """A proposed tool call — the gate point, harness-neutral."""

    tool_name: str
    input: Any = None


@dataclass
class Session:
    # Absolute path to the current working directory; "" is treated as
    # "unknown / no path" and bucketed into "no-path".
    cwd: str = ""
    # Absolute path to the project root, used to classify cwd against the
    # project boundary. "" means "unknown".
    project_root: str = ""
    messages: list[Message] = field(default_factory=list)


# The features dict POSTed to / computed by the daemon. Keys are kebab-case BDSL
# feature names; values are kebab-case BDSL space members — both match the
# data/bdsl/*.bdsl declarations verbatim.
FeatureDict = dict[str, str]


def _message_from_dict(d: dict[str, Any]) -> Message:
    return Message(
        # A message lacking a recognised role buckets to "" and is ignored by the
        # extractors, rather than KeyError-voiding the whole event.
        role=d.get("role", ""),
        tool_name=d.get("tool_name") or d.get("toolName"),
        input=d.get("input"),
        timestamp=d.get("timestamp"),
        result=d.get("result"),
    )


def event_and_session_from_payload(
    payload: dict[str, Any],
) -> tuple[AgentToolEvent, Session]:
    """Build an AgentToolEvent + Session from a wire payload an adapter POSTs.

    Accepts both snake_case (Python adapters) and the camelCase an existing TS
    adapter may send, so the same endpoint serves every harness.
    """
    event = AgentToolEvent(
        tool_name=payload.get("tool_name") or payload.get("toolName") or "",
        input=payload.get("input"),
    )
    sess = payload.get("session") or {}
    session = Session(
        cwd=sess.get("cwd") or sess.get("cwd_path") or "",
        project_root=sess.get("project_root") or sess.get("projectRoot") or "",
        messages=[_message_from_dict(m) for m in (sess.get("messages") or [])],
    )
    return event, session
