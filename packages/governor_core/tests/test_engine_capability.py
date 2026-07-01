"""A1 — the boot capability assertion + the digest-pinned engine image.

`_assert_engine_capable` is a pure inspection of the `initialize()` dict (exercised
directly, the `_block_category` pattern); a stub-skin `boot()` test then pins that boot
actually *calls* it, tolerates a `None` reply, and stashes `self.engine`."""

from __future__ import annotations

import pytest

from credence_governor_core import DEFAULT_SKIN_IMAGE
from credence_governor_core.log import ObservationLog
from credence_governor_core.session import (
    BrainSession,
    _REQUIRED_VERBS,
    _assert_engine_capable,
)

# A superset advertisement like a real skin's initialize() reply.
_FULL = sorted(_REQUIRED_VERBS | {"initialize", "shutdown", "expect", "condition"})


def _info(methods, **extra):
    return {"version": "0.1.0", "protocol": "1.12", "methods": methods, **extra}


# ── the pure assertion ──────────────────────────────────────────────────────
def test_passes_when_all_required_verbs_advertised():
    _assert_engine_capable(_info(_FULL))  # does not raise


def test_raises_when_no_methods_advertised():
    # An engine that advertises nothing is too old / not the skin — incapable, not "assume ok".
    for empty in ({}, _info([]), _info(None)):
        with pytest.raises(RuntimeError):
            _assert_engine_capable(empty)


def test_every_required_verb_is_individually_load_bearing():
    # Dropping ANY one of the six the governor drives must fail — no silent partial capability.
    for verb in _REQUIRED_VERBS:
        methods = [m for m in _FULL if m != verb]
        with pytest.raises(RuntimeError, match=verb):
            _assert_engine_capable(_info(methods))


# ── boot() wiring (stub skin; no real engine) ───────────────────────────────
class _FakeSkin:
    """Minimal skin: initialize() returns a canned info; the belief verbs return opaque handles."""

    def __init__(self, info):
        self._info = info
        self.initialized = False

    def initialize(self):
        self.initialized = True
        return self._info

    def _call(self, method, _params):
        if method == "structure_bma":
            return {"model_id": "m", "state_id": "s"}
        if method == "routing_init":
            return {"routing_state_id": "r"}
        return {"state_id": "s"}


def _session(tmp_path, info):
    # Empty brain_dir ⇒ no warm counts; empty log ⇒ no replay. Boot exercises only the wiring.
    return BrainSession(_FakeSkin(info), str(tmp_path), ObservationLog(str(tmp_path / "obs.jsonl")))


def test_boot_calls_assertion_and_populates_engine(tmp_path):
    sess = _session(tmp_path, _info(_FULL))
    sess.boot()
    assert sess.skin.initialized
    assert sess.engine == {"version": "0.1.0", "protocol": "1.12", "methods": _FULL}
    assert sess.waste == {"model_id": "m", "state_id": "s"}
    assert sess.routing == "r"


def test_boot_raises_on_incapable_engine_before_building_beliefs(tmp_path):
    sess = _session(tmp_path, _info([m for m in _FULL if m != "structure_decide"]))
    with pytest.raises(RuntimeError, match="structure_decide"):
        sess.boot()
    assert sess.waste is None  # assertion fires before any belief is built


def test_boot_tolerates_none_initialize(tmp_path):
    # initialize() → None must degrade to "no methods ⇒ raise", never AttributeError.
    class _NoneSkin(_FakeSkin):
        def initialize(self):
            return None

    sess = BrainSession(_NoneSkin(None), str(tmp_path), ObservationLog(str(tmp_path / "o.jsonl")))
    with pytest.raises(RuntimeError):
        sess.boot()


# ── the digest pin ──────────────────────────────────────────────────────────
def test_default_image_is_digest_pinned_not_latest():
    # Reproducible "current version": a bare :latest silently drifts across restarts.
    assert "@sha256:" in DEFAULT_SKIN_IMAGE
    assert ":latest" not in DEFAULT_SKIN_IMAGE
