"""install.py — idempotently register (or remove) the credence-governor hooks in a
Claude Code settings.json.

    credence-governor-cc-install            # -> ~/.claude/settings.json
    credence-governor-cc-install --project  # -> ./.claude/settings.json
    credence-governor-cc-install --path X    # -> X
    credence-governor-cc-install --uninstall

Registers THREE hooks (the pip-path equivalent of the plugin's hooks/hooks.json):
  • PreToolUse   → credence-governor-claude-code      (gates each tool call)
  • PostToolUse  → credence-governor-claude-code      (posts the measured outcome)
  • SessionStart → credence-governor-cc-session-start (warns if the daemon is down)

The same command serves PreToolUse and PostToolUse — it dispatches on hook_event_name.
Existing settings are preserved; we only touch hooks.PreToolUse / hooks.PostToolUse /
hooks.SessionStart, and dedupe by command.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

HOOK_COMMAND = "credence-governor-claude-code"  # PreToolUse
SESSION_START_COMMAND = "credence-governor-cc-session-start"  # SessionStart
_MATCHER = "*"  # all tools (PreToolUse)


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


def _add_event(settings: dict[str, Any], event: str, command: str, matcher: str | None) -> None:
    entries = settings.setdefault("hooks", {}).setdefault(event, [])
    if _command_present(entries, command):
        return
    entry: dict[str, Any] = {"hooks": [{"type": "command", "command": command}]}
    if matcher is not None:
        entry = {"matcher": matcher, **entry}
    entries.append(entry)


def _remove_event(settings: dict[str, Any], event: str, command: str) -> None:
    entries = settings.get("hooks", {}).get(event)
    if not entries:
        return
    for entry in entries:
        entry["hooks"] = [
            h
            for h in entry.get("hooks", [])
            if not (h.get("type") == "command" and h.get("command") == command)
        ]
    settings["hooks"][event] = [e for e in entries if e.get("hooks")]


def add(settings: dict[str, Any], command: str = HOOK_COMMAND) -> dict[str, Any]:
    _add_event(settings, "PreToolUse", command, _MATCHER)
    _add_event(settings, "PostToolUse", command, _MATCHER)
    _add_event(settings, "SessionStart", SESSION_START_COMMAND, None)
    return settings


def remove(settings: dict[str, Any], command: str = HOOK_COMMAND) -> dict[str, Any]:
    _remove_event(settings, "PreToolUse", command)
    _remove_event(settings, "PostToolUse", command)
    _remove_event(settings, "SessionStart", SESSION_START_COMMAND)
    return settings


def _target(args: argparse.Namespace) -> str:
    if args.path:
        return args.path
    if args.project:
        return os.path.join(os.getcwd(), ".claude", "settings.json")
    return os.path.join(os.path.expanduser("~"), ".claude", "settings.json")


def main() -> int:
    ap = argparse.ArgumentParser(description="Register the credence-governor Claude Code hooks.")
    ap.add_argument("--project", action="store_true", help="install into ./.claude/settings.json")
    ap.add_argument("--path", help="explicit settings.json path")
    ap.add_argument("--command", default=HOOK_COMMAND, help="PreToolUse hook command to register")
    ap.add_argument("--uninstall", action="store_true", help="remove the hooks instead")
    args = ap.parse_args()

    path = _target(args)
    settings = _load(path)
    settings = remove(settings, args.command) if args.uninstall else add(settings, args.command)
    _save(path, settings)
    verb = "removed from" if args.uninstall else "installed into"
    sys.stdout.write(f"credence-governor hooks (PreToolUse + PostToolUse + SessionStart) {verb} {path}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
