"""install.py — idempotently register (or remove) the PreToolUse hook in a Claude
Code settings.json.

    credence-governor-cc-install            # -> ~/.claude/settings.json
    credence-governor-cc-install --project  # -> ./.claude/settings.json
    credence-governor-cc-install --path X    # -> X
    credence-governor-cc-install --uninstall

The hook command defaults to the installed console script `credence-governor-claude-code`.
Existing settings are preserved; we only touch hooks.PreToolUse, and dedupe by command.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

HOOK_COMMAND = "credence-governor-claude-code"
_MATCHER = "*"  # all tools


def _load(path: str) -> dict[str, Any]:
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        text = fh.read().strip()
    return json.loads(text) if text else {}


def _save(path: str, data: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")


def _command_present(entries: list[dict[str, Any]], command: str) -> bool:
    for entry in entries:
        for h in entry.get("hooks", []):
            if h.get("type") == "command" and h.get("command") == command:
                return True
    return False


def add(settings: dict[str, Any], command: str = HOOK_COMMAND) -> dict[str, Any]:
    hooks = settings.setdefault("hooks", {})
    pre = hooks.setdefault("PreToolUse", [])
    if not _command_present(pre, command):
        pre.append({"matcher": _MATCHER, "hooks": [{"type": "command", "command": command}]})
    return settings


def remove(settings: dict[str, Any], command: str = HOOK_COMMAND) -> dict[str, Any]:
    pre = settings.get("hooks", {}).get("PreToolUse", [])
    for entry in pre:
        entry["hooks"] = [
            h for h in entry.get("hooks", []) if not (h.get("type") == "command" and h.get("command") == command)
        ]
    settings.get("hooks", {})["PreToolUse"] = [e for e in pre if e.get("hooks")]
    return settings


def _target(args: argparse.Namespace) -> str:
    if args.path:
        return args.path
    if args.project:
        return os.path.join(os.getcwd(), ".claude", "settings.json")
    return os.path.join(os.path.expanduser("~"), ".claude", "settings.json")


def main() -> int:
    ap = argparse.ArgumentParser(description="Register the credence-governor PreToolUse hook.")
    ap.add_argument("--project", action="store_true", help="install into ./.claude/settings.json")
    ap.add_argument("--path", help="explicit settings.json path")
    ap.add_argument("--command", default=HOOK_COMMAND, help="hook command to register")
    ap.add_argument("--uninstall", action="store_true", help="remove the hook instead")
    args = ap.parse_args()

    path = _target(args)
    settings = _load(path)
    settings = remove(settings, args.command) if args.uninstall else add(settings, args.command)
    _save(path, settings)
    verb = "removed from" if args.uninstall else "installed into"
    sys.stdout.write(f"credence-governor PreToolUse hook {verb} {path}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
