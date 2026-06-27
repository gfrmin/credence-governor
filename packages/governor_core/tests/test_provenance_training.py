"""test_provenance_training.py — the M2 provenance feature + cross-corpus training.

The robustness claim is NOT "the extractor decides trust" but "the extractor exposes
provenance as the `taint-source` feature, and the posterior learns read-own → benign
from benign-coding NEGATIVES while keeping attack recall". These tests pin the two
halves: (1) benign coding occupies a distinct provenance value (own/none) that attacks
do not, and (2) folding benign negatives drives that value's harm rate below the
external sources'. The corpus-scale check skips when ATBench is absent (CI).
"""

from __future__ import annotations

import os
from collections import defaultdict

import pytest

from credence_governor_core.config import HARM
from credence_governor_core.safety import extract_safety
from credence_governor_core.training.build_harm_brain import (
    accumulate,
    fold_benign_negatives,
)
from credence_governor_core.training.corpus import load_atbench
from credence_governor_core.training.fp_eval import BENIGN_CODING_CASES, benign_coding_calls

# The shipped harm feature set (6-tuple post-M4); ctx[2] == taint-source, ctx[3] == target-externality.
CTX_KEYS = HARM["feature_names"]

_PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CORPUS = os.path.join(_PKG, "data_corpora", "atbench_claw", "test.json")
_needs_corpus = pytest.mark.skipif(not os.path.exists(_CORPUS), reason="ATBench corpus not staged")

_EXTERNAL_SOURCES = {"web", "browser", "email", "message", "command-network", "marker",
                     "read-external", "command-external", "local-external"}


def test_benign_coding_never_looks_externally_sourced():
    # Whatever a benign coding call's taint, its provenance is never an EXTERNAL source
    # class — that is the value the posterior keys harm on, and benign coding must not
    # land there. (It is 'none' for clean calls, 'read-own'/'command-own' for read-then-act.)
    for c in BENIGN_CODING_CASES:
        src = extract_safety(c.event, c.session)["taint-source"]
        assert src not in _EXTERNAL_SOURCES, f"{c.name} mis-sourced as external: {src}"


def test_read_then_act_is_own_sourced():
    by_name = {c.name: c for c in BENIGN_CODING_CASES}
    for name in ("edit-security-code-after-read", "edit-file-after-reading-it"):
        src = extract_safety(by_name[name].event, by_name[name].session)["taint-source"]
        assert src == "read-own", f"{name} should be read-own, got {src}"


def test_fold_benign_negatives_adds_n0_only():
    counts: dict = defaultdict(lambda: [0, 0])
    n = fold_benign_negatives(counts, benign_coding_calls(), CTX_KEYS)
    assert n == len(BENIGN_CODING_CASES)
    assert sum(n1 for _, n1 in counts.values()) == 0          # negatives never add harm
    assert sum(n0 for n0, _ in counts.values()) == n


@_needs_corpus
def test_cross_corpus_training_separates_own_from_external():
    # Train on ATBench (attacks) + benign-coding (negatives) over the shipped 6-feature set.
    counts, _ = accumulate(load_atbench(_CORPUS), CTX_KEYS)
    fold_benign_negatives(counts, benign_coding_calls(), CTX_KEYS)

    by_src: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for ctx, (n0, n1) in counts.items():
        by_src[ctx[2]][0] += n0  # ctx[2] == taint-source
        by_src[ctx[2]][1] += n1

    def rate(src: str) -> float:
        n0, n1 = by_src[src]
        return n1 / (n0 + n1) if (n0 + n1) else 0.0

    # External provenance concentrates harm; own-sourced taint is markedly lower.
    assert rate("read-own") < 0.5
    for ext in ("web", "email", "message", "marker"):
        if sum(by_src[ext]):
            assert rate(ext) >= 0.6, f"{ext} should stay high-harm, got {rate(ext):.2f}"
    assert rate("read-own") < rate("read-unknown")  # locality discriminates within reads


@_needs_corpus
def test_distinctive_provenance_cells_are_benign():
    # The benign-coding cells with a DISTINCTIVE M2/M3 feature value (read-own) separate
    # cleanly even at curated-negative scale; generic cells (local-write/none, external-
    # send/internal) need coding-negative VOLUME (the real dogfood) and are not asserted.
    counts, _ = accumulate(load_atbench(_CORPUS), CTX_KEYS)
    fold_benign_negatives(counts, benign_coding_calls(), CTX_KEYS)
    for c in BENIGN_CODING_CASES:
        if c.name in ("edit-security-code-after-read", "edit-file-after-reading-it"):
            ctx = tuple(extract_safety(c.event, c.session)[k] for k in CTX_KEYS)
            n0, n1 = counts[ctx]
            assert n1 == 0, f"{c.name} read-own cell carries harm: {ctx} -> {(n0, n1)}"


@_needs_corpus
def test_target_externality_separates_external_send_at_the_extreme():
    # M3: external-send to an EXTERNAL target is the unambiguous-harm extreme; the
    # structure-BMA reads target-externality (ctx[3]) as its own feature.
    counts, _ = accumulate(load_atbench(_CORPUS), CTX_KEYS)
    by_te: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for ctx, (n0, n1) in counts.items():
        if ctx[0] == "external-send":
            by_te[ctx[3]][0] += n0
            by_te[ctx[3]][1] += n1
    ext_n0, ext_n1 = by_te["external"]
    assert ext_n1 / (ext_n0 + ext_n1) >= 0.9  # external-send to external target ~ always harm
