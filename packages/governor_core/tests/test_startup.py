"""The ready banner announces READY (not just "listening"), so the moment the daemon
starts actually governing is unmistakable. See __init__._print_banner / run()."""

from __future__ import annotations

from credence_governor_core import _print_banner


def test_banner_announces_ready_and_address():
    lines: list[str] = []
    _print_banner("127.0.0.1", 8787, "/brain", "/log", lines.append)
    text = "\n".join(lines)
    assert "READY" in text  # leads with the go-signal, not an ambiguous "listening"
    assert "127.0.0.1:8787" in text
