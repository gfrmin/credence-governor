"""test_cand_eval.py — the candidate-feature eval harness.

The harness scores a candidate ``(event, session) -> bool`` on two axes at once:
harm precision/recall/lift on attack corpora, and fire-rate (== false-positive
rate) on the all-negative benign-coding corpus. The synthetic-source tests pin
the metric arithmetic exactly; the benign-coding tests pin the FP-coupling that
makes this the M2/M3 measurement instrument. (ATBench-dependent numbers are not
asserted here — they live in the report, and the corpus is gitignored.)
"""

from __future__ import annotations

import math

from credence_governor_core.schema import AgentToolEvent, Session
from credence_governor_core.training.cand_eval import (
    BUILTIN_CANDIDATES,
    CorpusSource,
    EvalCall,
    benign_coding_source,
    from_safety_feature,
    score_candidate,
    score_pooled,
)


def _synthetic() -> CorpusSource:
    # 3 calls across 2 trajectories: 1 harmful send (t1), a benign read (t1), a
    # benign send in a SAFE trajectory (t2). A "fires on send" candidate then has a
    # known confusion matrix.
    calls = [
        EvalCall(AgentToolEvent("send", {}), Session(), "t1", is_safe=False, is_harm=True),
        EvalCall(AgentToolEvent("read", {}), Session(), "t1", is_safe=False, is_harm=False),
        EvalCall(AgentToolEvent("send", {}), Session(), "t2", is_safe=True, is_harm=False),
    ]
    return CorpusSource("synthetic", lambda: iter(calls))


def _fires_on_send(event: AgentToolEvent, _session: Session) -> bool:
    return event.tool_name == "send"


def test_metric_arithmetic_is_exact():
    m = score_candidate(_fires_on_send, _synthetic())
    assert m.n_calls == 3 and m.n_fire == 2 and m.n_harm == 1
    assert m.harm_precision == 0.5      # 1 of 2 fires is the harmful call
    assert m.harm_recall == 1.0         # caught the 1 harmful call
    assert math.isclose(m.lift, 1.5)    # 0.5 / (1/3 base rate)
    assert math.isclose(m.fire_rate, 2 / 3)
    assert m.traj_precision == 0.5      # t1 (unsafe) and t2 (safe) both fire
    assert m.traj_recall == 1.0         # the 1 unsafe trajectory fires


def test_candidate_exception_is_a_counted_non_fire():
    def boom(event, session):
        raise ValueError("candidate blew up")

    m = score_candidate(boom, _synthetic())
    assert m.n_fire == 0          # never crashes the eval
    assert m.n_error == m.n_calls  # ...but a systematically-broken candidate reads as broken


def test_benign_coding_fires_are_pure_false_positives():
    src = benign_coding_source()
    # external-send fires on the localhost-curl pathology (post-M3, the security-edit is
    # a local-write, not external-send); on an all-benign corpus every fire is an FP.
    m = score_candidate(BUILTIN_CANDIDATES["action=external-send"], src)
    assert m.n_harm == 0
    assert m.n_fire >= 1
    assert m.fire_rate > 0
    assert m.examples_fp  # the offending coding call is surfaced
    assert math.isnan(m.harm_recall)  # no harm to recall in an all-benign corpus


def test_clean_feature_has_zero_coding_fp():
    # tainted-external-target requires untrusted tokens reaching an external send —
    # benign coding never trips it. This is the property M2/M3 must give the other
    # features.
    m = score_candidate(BUILTIN_CANDIDATES["tainted-external-target"], benign_coding_source())
    assert m.n_fire == 0
    assert m.fire_rate == 0.0


def test_from_safety_feature_builds_a_working_candidate():
    cand = from_safety_feature("action-class", "read-only")
    fires = cand(AgentToolEvent("read", {"file_path": "/x"}), Session())
    assert fires is True
    assert from_safety_feature("action-class", "read-only")(
        AgentToolEvent("bash", {"command": "rm -rf x"}), Session()) is False


def test_pooled_sums_across_sources():
    pooled = score_pooled(_fires_on_send, [_synthetic(), _synthetic()])
    assert pooled.n_calls == 6 and pooled.n_fire == 4 and pooled.n_harm == 2


def test_pooled_traj_metrics_survive_session_id_collision():
    # Both synthetic sources reuse session ids t1/t2; pooling must NOT collapse them
    # into 2 buckets (the source-index prefix keeps them distinct), so there are 2
    # unsafe trajectories (one t1 per source), both firing.
    pooled = score_pooled(_fires_on_send, [_synthetic(), _synthetic()])
    assert pooled.traj_recall == 1.0      # both unsafe trajectories fire
    assert pooled.traj_precision == 0.5   # 2 unsafe + 2 safe trajectories all fire
    # 4 distinct trajectories total (2 per source), not 2 collapsed
    single = score_candidate(_fires_on_send, _synthetic())
    assert pooled.n_calls == 2 * single.n_calls
