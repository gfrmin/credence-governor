"""decide_sync tags each decision with a block category (safety vs waste) so the body can
make a waste-block overridable while keeping safety-blocks hard. _block_category is a pure
inspection of the (server-side) attack-pattern features — no belief arithmetic, no adapter
logic. It keys on the attack signals (taint / exfil / injection), NOT on action-class: a
destructive-but-not-attack action stays OVERRIDABLE."""

from __future__ import annotations

import threading
import types

from credence_governor_core.daemon import Daemon, _block_category
from credence_governor_core.log import ObservationLog


def test_block_category_safety_only_on_attack_pattern_features():
    assert _block_category({"taint-flow": "tainted-sink"}) == "safety"
    assert _block_category({"taint-flow": "tainted-external-target"}) == "safety"
    assert _block_category({"cred-exfil-chain": "yes"}) == "safety"
    assert _block_category({"injected-imperative": "yes"}) == "safety"


def test_destructive_action_without_attack_signal_stays_waste():
    # a repeated `rm`/exec flagged as a loop is WASTE (overridable), not hard safety —
    # action-class is the action type, not the block's motivation.
    assert _block_category({"action-class": "delete", "taint-flow": "none"}) == "waste"
    assert _block_category({"action-class": "external-send", "taint-flow": "none", "cred-exfil-chain": "no"}) == "waste"
    assert _block_category({"action-class": "read-only"}) == "waste"
    assert _block_category({}) == "waste"


def test_decide_response_carries_category(tmp_path):
    session = types.SimpleNamespace(decide=lambda *a, **k: "block")
    log = ObservationLog(str(tmp_path / "o.jsonl"))
    daemon = Daemon(session, log, threading.Lock())
    safety = daemon.decide_sync({"features": {"taint-flow": "tainted-external-target"}})
    assert safety["action"] == "block" and safety["category"] == "safety"
    waste = daemon.decide_sync({"features": {"action-class": "delete", "taint-flow": "none"}})
    assert waste["category"] == "waste"
