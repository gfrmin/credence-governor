"""test_log_outcomes.py — replay_outcome_contexts: the per-event outcome
selection (source precedence, last-within-source), the good-bit rule, and
the skips (ambiguous, unknown source, missing features)."""

from credence_governor_core.log import ObservationLog


def _outcome(eid, source, **fields):
    base = {"event_type": "outcome", "in_response_to": eid, "source": source,
            "completed": None, "latency_s": None, "spend_usd": None,
            "reverted": None, "retries": None, "error": None}
    base.update(fields)
    return base


def make_log(tmp_path, records):
    log = ObservationLog(str(tmp_path / "log.jsonl"))
    for r in records:
        log.append(r)
    return log


def test_good_bit_rule(tmp_path):
    log = make_log(tmp_path, [
        {"event_type": "tool-proposed", "event_id": "kept", "features": {"tool-name": "bash"}},
        {"event_type": "tool-proposed", "event_id": "undone", "features": {"tool-name": "edit"}},
        {"event_type": "tool-proposed", "event_id": "murky", "features": {"tool-name": "read"}},
        {"event_type": "tool-proposed", "event_id": "failed", "features": {"tool-name": "bash"}},
        _outcome("kept", "grounding", completed=True, reverted=False),
        _outcome("undone", "grounding", completed=False, reverted=True),
        _outcome("murky", "grounding", completed=None, reverted=None),
        # completed=False WITHOUT revert evidence: excluded, not counted 0
        _outcome("failed", "grounding", completed=False, reverted=False),
    ])
    out = {o["event_id"]: o["good"] for o in log.replay_outcome_contexts()}
    assert out == {"kept": 1, "undone": 0}


def test_source_precedence_and_last_within_source(tmp_path):
    log = make_log(tmp_path, [
        {"event_type": "tool-proposed", "event_id": "e1", "features": {"tool-name": "bash"}},
        # result-hook says completed; grounding later says reverted:
        # grounding outranks, even though it arrived later
        _outcome("e1", "result-hook", completed=True),
        _outcome("e1", "grounding", reverted=True),
        # a second grounding record for the same event: LAST within the
        # winning source wins
        _outcome("e1", "grounding", completed=True, reverted=False),
    ])
    out = log.replay_outcome_contexts()
    assert out == [{"event_id": "e1", "features": {"tool-name": "bash"}, "good": 1}]


def test_lower_rank_never_displaces_higher(tmp_path):
    log = make_log(tmp_path, [
        {"event_type": "tool-proposed", "event_id": "e1", "features": {"tool-name": "bash"}},
        _outcome("e1", "grounding", reverted=True),
        _outcome("e1", "result-hook", completed=True),   # later but lower rank
    ])
    assert log.replay_outcome_contexts()[0]["good"] == 0


def test_unknown_source_and_missing_features_skipped(tmp_path):
    log = make_log(tmp_path, [
        {"event_type": "tool-proposed", "event_id": "e1", "features": {"tool-name": "bash"}},
        _outcome("e1", "vibes", completed=True),          # not evidence-grade
        _outcome("orphan", "grounding", completed=True),  # no tool-proposed
    ])
    assert log.replay_outcome_contexts() == []


def test_output_in_first_arrival_order(tmp_path):
    log = make_log(tmp_path, [
        {"event_type": "tool-proposed", "event_id": "a", "features": {"tool-name": "bash"}},
        {"event_type": "tool-proposed", "event_id": "b", "features": {"tool-name": "edit"}},
        _outcome("b", "result-hook", completed=True),
        _outcome("a", "grounding", completed=True, reverted=False),
        _outcome("b", "grounding", completed=True, reverted=False),
    ])
    assert [o["event_id"] for o in log.replay_outcome_contexts()] == ["b", "a"]
