"""test_join.py — the 3-way join, corpus stats, category recompute."""

from credence_governor_core.daemon import _block_category

from join import corpus_stats, join


def _proposed(eid, features):
    return {"event_type": "tool-proposed", "event_id": eid, "features": features}


def _decision(eid, action):
    return {"event_type": "decision", "in_response_to": eid, "action": action}


def _outcome(eid, source="grounding", **fields):
    base = {"event_type": "outcome", "in_response_to": eid, "source": source,
            "completed": None, "latency_s": None, "spend_usd": None,
            "reverted": None, "retries": None, "error": None}
    base.update(fields)
    return base


WASTE = {"tool-name": "bash"}
SAFETY = {"tool-name": "bash", "taint-source": "web", "injected-imperative": "yes"}


def test_join_and_orphans():
    records = [
        _proposed("a", WASTE), _decision("a", "block"),
        _outcome("a", completed=True, reverted=False),
        _outcome("a", source="result-hook", latency_s=0.5),   # multi-outcome
        _proposed("b", SAFETY), _decision("b", "proceed"),
        _outcome("b", reverted=True),
        _proposed("undecided", WASTE),                        # no decision
        _decision("ghost", "ask"),                            # no proposal
        _outcome("ghost2", completed=True),                   # no proposal
        {"event_type": "membrane-shadow", "in_response_to": "a",
         "utility_form": "latent@1", "action": "block"},      # skipped
        {"event_type": "turn-cost", "usd": 1.0},              # skipped
    ]
    rows, orphans = join(records)
    assert [r.event_id for r in rows] == ["a", "b"]
    assert rows[0].action == "block"
    assert rows[0].outcome.label == "accepted"
    assert rows[0].outcome.latency_s == 0.5
    assert rows[1].outcome.label == "reverted"
    assert rows[1].category == "safety" == _block_category(SAFETY)
    assert rows[0].category == "waste"
    assert orphans == {"decisions_without_proposal": 1,
                       "outcomes_without_proposal": 1,
                       "proposals_without_decision": 1}


def test_corpus_stats_hand_check():
    records = []
    # 3 blocks: 2 on accepted, 1 on reverted; 6 proceeds: 5 accepted-ish mix
    for i, (action, outcome_fields) in enumerate([
        ("block", {"completed": True}),
        ("block", {"completed": True}),
        ("block", {"reverted": True}),
        ("proceed", {"completed": True}),
        ("proceed", {"completed": True}),
        ("proceed", {"reverted": True}),
        ("proceed", {}),                      # ambiguous
        ("proceed", None),                    # ungrounded
        ("ask", {"completed": True}),
    ]):
        eid = f"e{i}"
        records.append(_proposed(eid, WASTE))
        records.append(_decision(eid, action))
        if outcome_fields is not None:
            records.append(_outcome(eid, **outcome_fields))
    rows, _ = join(records)
    stats = corpus_stats(rows)
    assert stats["decisions"] == 9
    assert stats["per_action"]["block"] == {"accepted": 2, "reverted": 1}
    assert stats["per_action"]["proceed"] == {
        "accepted": 2, "reverted": 1, "ambiguous": 1, "ungrounded": 1}
    assert stats["would_block_rate"] == 3 / 9
    assert stats["decisive"] == 7   # 3 block + 3 proceed + 1 ask decisive rows
    assert stats["outcome_justified_blocks"] == 1
    assert stats["reverted_total"] == 2


def test_category_recompute_on_legacy_keysets():
    """Coding rules inert on a bare 6-key dict, hot on a cred-exfil shape —
    pinned against the daemon's own _block_category."""
    legacy6 = {"tool-name": "bash", "working-directory-relative": "project-root",
               "parent-tool-call-name": "none", "recent-repetition-count": "rep-0",
               "recent-identical-call-count": "ident-0",
               "time-since-last-user-message": "lt-30s"}
    exfil15 = dict(legacy6, **{
        "coding-action-class": "credential-access",
        "egress-destination": "external-unknown",
        "target-sensitivity": "credential-store",
        "taint-source": "none", "taint-flow": "none",
        "injected-imperative": "no", "cred-exfil-chain": "no",
        "action-class": "read-only", "target-externality": "none"})
    rows, _ = join([
        _proposed("old", legacy6), _decision("old", "block"),
        _proposed("new", exfil15), _decision("new", "block"),
    ])
    assert rows[0].category == "waste"       # rules inert without coding keys
    assert rows[1].category == "safety"      # exfil shape is hot
