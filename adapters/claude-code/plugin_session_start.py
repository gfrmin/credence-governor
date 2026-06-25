#!/usr/bin/env python3
"""plugin_session_start.py — Claude Code *plugin* entry point for the SessionStart hook.

Mirror of plugin_hook.py: Claude Code runs `python3 ${CLAUDE_PLUGIN_ROOT}/plugin_session_start.py`
(see hooks/hooks.json). We put this directory on sys.path and delegate to the same main()
the pip console script `credence-governor-cc-session-start` uses — one implementation, two
install paths. Fail-open: any import problem exits 0 and emits nothing, so a session never
breaks because the hook could not load.
"""

from __future__ import annotations

import os
import sys


def _main() -> int:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        from credence_governor_claude_code.session_start import main
    except Exception:  # never let a bundling/import problem break a session
        return 0
    return main()


if __name__ == "__main__":
    raise SystemExit(_main())
