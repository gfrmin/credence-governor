# Role: eval
"""streams.py — the labeled event streams every governor is scored on.

Two streams in Phase 1, both yielding the SAME LabeledCall shape so a governor sees
identical inputs regardless of provenance (the apples-to-apples invariant):

  * benign-capture (REAL) — the agent's own captured Claude Code traffic
    (~/.credence-governor/raw_events.jsonl). Benign-by-assumption real dev work, so a
    gate here is a FALSE-BLOCK. This is the headline number a buyer cannot wave away:
    how much real work each governor interrupts. Validate the assumption on a sample.
  * red-team (DECLARED) — the coding attack corpus (RED_TEAM_CASES). is_harm=True, so a
    gate here is a CATCH (harm recall). Declared, not captured — tagged honestly.

Loaders reuse the governor's own surfaces: capture_corpus.load_capture (the same
re-extraction path the harm-brain training uses) and the shipped red_team set.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass

from credence_governor_core.schema import AgentToolEvent, Session
from credence_governor_core.training.capture_corpus import load_capture

DEFAULT_CAPTURE = os.path.expanduser("~/.credence-governor/raw_events.jsonl")


@dataclass
class LabeledCall:
    event: AgentToolEvent
    session: Session
    cid: str            # stable id (for dedup + per-call attribution)
    is_harm: bool       # ground-truth label for this call
    stream: str         # "benign-capture" | "red-team"
    source: str         # "real" | "declared" | "public"
    threat_class: str = ""


def benign_capture(path: str = DEFAULT_CAPTURE, limit: int | None = None) -> Iterator[LabeledCall]:
    """Real captured traffic as an all-NEGATIVE stream — every gate is a false-block.
    Streams the (2 GB+) capture line-by-line via load_capture (truncated/duplicate
    records already filtered there)."""
    for i, (event, session) in enumerate(load_capture(path)):
        if limit is not None and i >= limit:
            return
        yield LabeledCall(event, session, f"cap-{i}", is_harm=False,
                          stream="benign-capture", source="real")


def red_team() -> Iterator[LabeledCall]:
    """The declared coding attack corpus as an all-POSITIVE stream — every gate is a catch."""
    from credence_governor_core.training.red_team import RED_TEAM_CASES

    for c in RED_TEAM_CASES:
        yield LabeledCall(c.event, c.session, c.name, is_harm=True,
                          stream="red-team", source="declared", threat_class=c.threat_class)
