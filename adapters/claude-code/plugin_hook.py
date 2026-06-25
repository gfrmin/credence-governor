#!/usr/bin/env python3
"""plugin_hook.py — Claude Code *plugin* entry point for the credence-governor hook.

When installed as a plugin, Claude Code sets ${CLAUDE_PLUGIN_ROOT} to this directory
and runs `python3 ${CLAUDE_PLUGIN_ROOT}/plugin_hook.py` (see hooks/hooks.json). The
bundled `credence_governor_claude_code` package is pure stdlib, so we just put this
directory on sys.path and delegate to the very same main() the pip console script
`credence-governor-claude-code` uses — one implementation, two install paths (no
duplicated hook logic, no pip install needed for the plugin).

Fail-open is preserved end to end: if the bundled package can't be imported for any
reason we exit 0 and emit nothing, leaving the tool call to Claude Code's normal flow.
"""

from __future__ import annotations

import os
import sys


def _main() -> int:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        from credence_governor_claude_code.hook import main
    except Exception:  # never let a bundling/import problem block a tool call
        return 0
    return main()


if __name__ == "__main__":
    raise SystemExit(_main())
