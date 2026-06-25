"""credence-governor-claude-code — the Claude Code adapter.

A thin subprocess-hook shim: it translates Claude Code's native PreToolUse events
into the harness-neutral wire shape and asks the governor daemon (credence-governor-core)
for a proceed/block/ask decision. Carries no probabilistic code and no feature logic
— extraction is server-side in the daemon (DRY). The adapter's only job is
native-events -> neutral schema (+ render the decision).
"""

from __future__ import annotations

from .hook import handle, main
from .transcript import messages_from_transcript, session_from_hook

__all__ = ["main", "handle", "session_from_hook", "messages_from_transcript"]
