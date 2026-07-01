"""Version negotiation — the governor degrades against an older engine instead of crashing.

The contract (docs/engine-wire-requests.md § version negotiation) has two mechanisms, split by
what the engine bump adds:

  * new *verb* (R2, `structure_expect`) → **detect-and-record**: calling a missing verb errors,
    so `_assert_engine_capable` records the advertised optional subset and consumers gate on it.
  * new *key* on an existing verb (R1, `tail` on `structure_decide`) → **always send both**: the
    verb is advertised on both versions so method-detection is blind to the key; decide() always
    sends the scalar `expected_repeats` fallback alongside the `tail` coordinate, so a `1.12`
    engine that ignores the key still has the scalar. No capability check for the key.

These tests pin both: an optional verb's absence never raises, and decide()'s payload always
carries the scalar fallback while the `tail` coordinate stays latent until a tail belief is booted.
"""

from __future__ import annotations

from credence_governor_core.config import UTILITY
from credence_governor_core.log import ObservationLog
from credence_governor_core.session import (
    _OPTIONAL_VERBS,
    _REQUIRED_VERBS,
    BrainSession,
    _assert_engine_capable,
)

_FULL = sorted(_REQUIRED_VERBS | {"initialize", "shutdown", "expect", "condition"})  # a 1.12-shaped reply


def _info(methods, **extra):
    return {"version": "0.1.0", "protocol": "1.12", "methods": methods, **extra}


# ── R2: optional verbs are recorded, never required ─────────────────────────
def test_optional_absent_boots_and_records_empty():
    # A 1.12 engine (no structure_expect) must NOT raise — the whole point of assert-or-degrade.
    caps = _assert_engine_capable(_info(_FULL))
    assert caps == frozenset()


def test_optional_present_is_recorded():
    caps = _assert_engine_capable(_info(sorted(set(_FULL) | {"structure_expect"})))
    assert "structure_expect" in caps
    assert caps <= _OPTIONAL_VERBS  # only *known* optional verbs are surfaced, not arbitrary extras


def test_optional_and_required_are_not_one_check():
    # Required missing → raise; optional missing → fine. Collapsing them would crash on skew.
    assert _assert_engine_capable(_info(_FULL)) == frozenset()  # optional missing: ok
    try:
        _assert_engine_capable(_info([m for m in _FULL if m != "structure_decide"]))
    except RuntimeError:
        pass
    else:  # pragma: no cover
        raise AssertionError("a missing REQUIRED verb must still raise")


# ── boot() records caps and exposes supports() ──────────────────────────────
class _RecordingSkin:
    """Records every _call's params; returns minimal valid replies (incl. a decide action)."""

    def __init__(self, info):
        self._info = info
        self.calls: list[tuple[str, dict]] = []

    def initialize(self):
        return self._info

    def _call(self, method, params):
        self.calls.append((method, params))
        if method == "structure_bma":
            return {"model_id": "m", "state_id": "s"}
        if method == "routing_init":
            return {"routing_state_id": "r"}
        if method == "structure_decide":
            return {"action": "proceed"}
        return {"state_id": "s"}

    def last(self, method):
        return next(p for m, p in reversed(self.calls) if m == method)


def _session(tmp_path, info):
    return BrainSession(_RecordingSkin(info), str(tmp_path), ObservationLog(str(tmp_path / "o.jsonl")))


def test_boot_degrades_when_optional_absent(tmp_path):
    sess = _session(tmp_path, _info(_FULL))  # 1.12-shaped: no optional verbs
    sess.boot()
    assert sess.caps == frozenset()
    assert sess.supports("structure_expect") is False


def test_boot_records_optional_when_present(tmp_path):
    sess = _session(tmp_path, _info(sorted(set(_FULL) | {"structure_expect"})))  # 1.13-shaped
    sess.boot()
    assert sess.supports("structure_expect") is True


# ── R1: decide() always sends the scalar fallback; the tail key is latent ────
def test_decide_always_sends_scalar_fallback(tmp_path):
    # expected_repeats is ALWAYS in the payload, at its 0.0 default (== today's myopic decision,
    # since the engine defaults an absent expected_repeats to 0).
    sess = _session(tmp_path, _info(_FULL))
    sess.boot()
    sess.decide({"tool": "bash"})
    p = sess.skin.last("structure_decide")
    assert p["expected_repeats"] == UTILITY["expected_repeats"] == 0.0


def test_decide_omits_tail_key_while_belief_unbooted(tmp_path):
    # self.tail is None this release (plumbing shipped dark) ⇒ the `tail` key is NEVER sent,
    # even when tail_features are supplied ⇒ decision-identical against today's engine.
    sess = _session(tmp_path, _info(_FULL))
    sess.boot()
    assert sess.tail is None
    sess.decide({"tool": "bash"}, tail_features={"ident": "ident-3plus"})
    assert "tail" not in sess.skin.last("structure_decide")


def test_decide_sends_both_scalar_and_tail_once_belief_present(tmp_path):
    # When a tail belief IS configured (the follow-up's job) + tail_features given, decide()
    # sends BOTH the scalar fallback and the `tail` coordinate — the always-send-both contract.
    sess = _session(tmp_path, _info(_FULL))
    sess.boot()
    sess.tail = {"model_id": "mt", "state_id": "st"}  # simulate a booted continuation belief
    sess.decide({"tool": "bash"}, tail_features={"ident": "ident-3plus"})
    p = sess.skin.last("structure_decide")
    assert p["expected_repeats"] == 0.0  # scalar fallback still present alongside the coordinate
    assert p["tail"] == {"model_id": "mt", "state_id": "st", "features": {"ident": "ident-3plus"}}


def test_decide_tail_key_needs_tail_features_too(tmp_path):
    # A booted belief but no per-call tail_features ⇒ still no key (nothing to read at what context).
    sess = _session(tmp_path, _info(_FULL))
    sess.boot()
    sess.tail = {"model_id": "mt", "state_id": "st"}
    sess.decide({"tool": "bash"})
    assert "tail" not in sess.skin.last("structure_decide")
