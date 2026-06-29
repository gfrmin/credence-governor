# Role: eval
"""Drift guard (§5.4): the Python profile mirror must match adapters/openclaw/src/profile.ts
(the source of truth). If the TS PRESETS change and this mirror doesn't, this test fails."""

from __future__ import annotations

import os
import re

import pytest

from profiles import PRESETS, PROFILE_TS

_KEYMAP = {"reward": "reward", "lambda": "lam", "q": "q", "harm": "harm", "w_time": "w_time"}


def _parse_ts_presets(text: str) -> dict[str, dict]:
    """Extract the PRESETS object literal from profile.ts: name -> {field: float}."""
    block = re.search(r"PRESETS[^{]*\{(.*?)\n\}", text, re.S)
    assert block, "could not locate PRESETS in profile.ts"
    out = {}
    for name, body in re.findall(r'"?([\w-]+)"?\s*:\s*\{([^}]*)\}', block.group(1)):
        fields = {}
        for k, v in re.findall(r"(\w+)\s*:\s*([0-9.]+)", body):
            if k in _KEYMAP:
                fields[_KEYMAP[k]] = float(v)
        if fields:
            out[name] = fields
    return out


def test_python_presets_match_typescript_source():
    if not os.path.exists(PROFILE_TS):
        pytest.skip(f"profile.ts not found at {PROFILE_TS}")
    ts = _parse_ts_presets(open(PROFILE_TS).read())
    assert ts, "parsed zero presets from profile.ts"
    for name, fields in ts.items():
        assert name in PRESETS, f"profile.ts preset '{name}' missing from the Python mirror"
        p = PRESETS[name]
        for attr, val in fields.items():
            assert getattr(p, attr) == pytest.approx(val), \
                f"{name}.{attr}: python {getattr(p, attr)} != ts {val} (drift)"
