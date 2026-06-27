"""cand_eval.py — score a candidate harm feature, per-corpus and pooled.

Generalises credence_pi_eval's ``eval_call_feature`` / ``eval_traj_feature`` off
the raw ATBench record onto the governor's neutral ``(AgentToolEvent, Session)``
stream. A candidate is therefore evaluated under the SAME causal runtime contract
the live extractor obeys —

    candidate(event, session_so_far) -> bool

— across EVERY adapted corpus, not one. This is what makes M2/M3 features measured
rather than asserted: define the predicate, score it, judge the lift.

Two things the reference harness could not do, both enabled here:

  * **Call-level harm labels.** The reason-attribution port (``localize_harm``)
    gives the human-named harmful call, so precision is "fires ON the harmful
    action", not the weaker "fires somewhere in an unsafe trajectory".
  * **Benign coding as a corpus.** ``BENIGN_CODING_CASES`` enters as an all-negative
    source, so a candidate's *coding false-positive rate* is scored in the same
    pass as its attack recall. A good harm feature has high harm-recall on the
    attack corpora AND a low fire-rate on benign coding — the M2/M3 objective, on
    one screen.

    run:  python -m credence_governor_core.training.cand_eval <atbench.json>
"""

from __future__ import annotations

import json
import math
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

from ..safety import extract_safety
from ..schema import AgentToolEvent, Session
from .build_harm_brain import localize_harm
from .corpus import iter_atbench_calls, load_atbench
from .fp_eval import BENIGN_CODING_CASES

# A candidate harm feature: a causal predicate over the proposed call + prior session.
Candidate = Callable[[AgentToolEvent, Session], bool]


@dataclass
class EvalCall:
    event: AgentToolEvent
    session: Session
    session_id: str
    is_safe: bool   # trajectory-level label (constant within a session)
    is_harm: bool   # call-level: this call IS the human-localized harmful action


@dataclass
class CorpusSource:
    name: str
    calls: Callable[[], Iterator[EvalCall]]


# ── sources ──────────────────────────────────────────────────────────────────
def atbench_source(path: str, name: str = "atbench") -> CorpusSource:
    def gen() -> Iterator[EvalCall]:
        for i, record in enumerate(load_atbench(path)):
            sid = record.get("trajectory", {}).get("session_id") or f"atbench-{i}"
            unsafe = not bool(record.get("labels", {}).get("is_safe", True))
            harm = localize_harm(record) if unsafe else set()
            for call in iter_atbench_calls(record, sid):
                yield EvalCall(call.event, call.session, sid, not unsafe, call.idx in harm)
    return CorpusSource(name, gen)


def benign_coding_source() -> CorpusSource:
    """The coding-agent FP corpus as an all-negative source: every fire is a false
    positive. Fire-rate here is the coding false-positive rate."""
    def gen() -> Iterator[EvalCall]:
        for c in BENIGN_CODING_CASES:
            yield EvalCall(c.event, c.session, c.name, is_safe=True, is_harm=False)
    return CorpusSource("benign-coding", gen)


# ── built-in candidates (the existing 4 features, as the baseline to beat) ────
def from_safety_feature(key: str, value: str) -> Candidate:
    """A candidate that fires when the live extractor assigns ``key == value``."""
    def fires(event: AgentToolEvent, session: Session) -> bool:
        return extract_safety(event, session).get(key) == value
    return fires


BUILTIN_CANDIDATES: dict[str, Candidate] = {
    "injected-imperative": from_safety_feature("injected-imperative", "yes"),
    "tainted-external-target": from_safety_feature("taint-flow", "tainted-external-target"),
    "cred-exfil-chain": from_safety_feature("cred-exfil-chain", "yes"),
    "action=external-send": from_safety_feature("action-class", "external-send"),
    "any-taint": lambda e, s: extract_safety(e, s)["taint-flow"] != "none",
}


# ── scoring ──────────────────────────────────────────────────────────────────
def _safe_div(a: float, b: float) -> float:
    return a / b if b else math.nan


@dataclass
class Metrics:
    corpus: str
    n_calls: int = 0
    n_fire: int = 0
    n_harm: int = 0
    harm_precision: float = math.nan   # P(is_harm | fires) — fires ON the harmful call
    harm_recall: float = math.nan      # P(fires | is_harm)
    lift: float = math.nan             # harm_precision / call-level base rate
    fire_rate: float = math.nan        # n_fire / n_calls (== FP rate on an all-benign corpus)
    traj_precision: float = math.nan   # reference parity: unsafe traj among traj that fire
    traj_recall: float = math.nan
    examples_fp: list[str] = field(default_factory=list)


def score_candidate(candidate: Candidate, source: CorpusSource) -> Metrics:
    m = Metrics(corpus=source.name)
    tp = 0
    traj_fire: dict[str, bool] = {}
    traj_unsafe: dict[str, bool] = {}
    for ec in source.calls():
        m.n_calls += 1
        m.n_harm += ec.is_harm
        traj_unsafe[ec.session_id] = not ec.is_safe
        traj_fire.setdefault(ec.session_id, False)
        try:
            fired = bool(candidate(ec.event, ec.session))
        except Exception:
            fired = False
        if fired:
            m.n_fire += 1
            traj_fire[ec.session_id] = True
            if ec.is_harm:
                tp += 1
            elif len(m.examples_fp) < 5:
                blob = json.dumps(ec.event.input)[:90] if ec.event.input is not None else ""
                m.examples_fp.append(f"{ec.event.tool_name} :: {blob}")
    m.harm_precision = _safe_div(tp, m.n_fire)
    m.harm_recall = _safe_div(tp, m.n_harm)
    m.lift = _safe_div(m.harm_precision, _safe_div(m.n_harm, m.n_calls))
    m.fire_rate = _safe_div(m.n_fire, m.n_calls)
    tf_u = sum(1 for s in traj_fire if traj_fire[s] and traj_unsafe[s])
    tf = sum(1 for s in traj_fire if traj_fire[s])
    n_u = sum(1 for s in traj_unsafe if traj_unsafe[s])
    m.traj_precision = _safe_div(tf_u, tf)
    m.traj_recall = _safe_div(tf_u, n_u)
    return m


def score_pooled(candidate: Candidate, sources: list[CorpusSource]) -> Metrics:
    """Score across all sources as one stream (pooled precision/recall/lift)."""
    def pooled() -> Iterator[EvalCall]:
        for src in sources:
            yield from src.calls()
    return score_candidate(candidate, CorpusSource("pooled", pooled))


def _fmt(x: float) -> str:
    return "  —  " if isinstance(x, float) and math.isnan(x) else f"{x:.2f}"


def report(candidates: dict[str, Candidate], sources: list[CorpusSource]) -> None:
    for label, cand in candidates.items():
        print(f"\n=== candidate: {label} ===")
        print(f"{'corpus':<16}{'calls':>7}{'fire':>6}{'harm':>6}"
              f"{'h-prec':>8}{'h-rec':>7}{'lift':>7}{'fire%':>7}")
        for src in sources:
            m = score_candidate(cand, src)
            print(f"{m.corpus:<16}{m.n_calls:>7}{m.n_fire:>6}{m.n_harm:>6}"
                  f"{_fmt(m.harm_precision):>8}{_fmt(m.harm_recall):>7}{_fmt(m.lift):>7}{_fmt(m.fire_rate):>7}")
            if m.corpus == "benign-coding" and m.examples_fp:
                print(f"    coding FP: {' | '.join(m.examples_fp)}")


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    sources = [benign_coding_source()]
    if argv:
        sources.insert(0, atbench_source(argv[0]))
    report(BUILTIN_CANDIDATES, sources)
    return 0


if __name__ == "__main__":
    sys.exit(main())
