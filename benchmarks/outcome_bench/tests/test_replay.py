"""test_replay.py — chronological replay order, verdict interleaving,
determinism (hermetic: a fake session, no subprocess)."""

from replay import replay_decisions


class FakeSession:
    def __init__(self):
        self.calls: list[tuple] = []
        self._n = 0

    def decide(self, features, harm_features=None, profile=None,
               tail_features=None):
        self.calls.append(("decide", dict(features)))
        self._n += 1
        return "proceed" if self._n % 2 else "block"

    def observe(self, features, observation):
        self.calls.append(("observe", dict(features), observation))


RECORDS = [
    {"event_type": "tool-proposed", "event_id": "e1",
     "features": {"tool-name": "bash"}},
    {"event_type": "decision", "in_response_to": "e1", "action": "block"},
    {"event_type": "user-responded", "in_response_to": "e1", "response": "no"},
    {"event_type": "outcome", "in_response_to": "e1", "source": "grounding",
     "completed": True},                       # inert for replay
    {"event_type": "membrane-shadow", "in_response_to": "e1",
     "action": "block", "utility_form": "latent@1"},   # inert
    {"event_type": "tool-proposed", "event_id": "e2",
     "features": {"tool-name": "edit"}},
    {"event_type": "user-responded", "in_response_to": "missing",
     "response": "yes"},                       # unmatched: skipped
    {"event_type": "user-responded", "in_response_to": "e2",
     "response": "timeout"},                   # not a label: skipped
]


def test_order_and_interleave():
    sess = FakeSession()
    decisions = replay_decisions(RECORDS, sess)
    assert list(decisions) == ["e1", "e2"]
    # the verdict tick lands BETWEEN the two decides, at its log position
    assert [c[0] for c in sess.calls] == ["decide", "observe", "decide"]
    assert sess.calls[1][2] == 0               # response "no" -> 0
    assert sess.calls[1][1] == {"tool-name": "bash"}  # the judged event's features


def test_determinism_same_records_same_decisions():
    a = replay_decisions(RECORDS, FakeSession())
    b = replay_decisions(RECORDS, FakeSession())
    assert a == b
