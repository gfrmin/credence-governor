"""test_provenance_training.py — the provenance feature in the coding-native model.

The robustness claim is NOT "the extractor decides trust" but "the extractor exposes
provenance as the `taint-source` feature, and the coding-native posterior learns
read-own/none → benign while keeping external-sourced attack recall". These tests pin:
(1) benign coding occupies a non-external provenance value attacks do not, and (2) the
coding-native build (build_coding: declared red-team n1 + curated benign n0) deposits
harm in external-provenance cells and never in the own/none benign cells. No ATBench:
the coding body's brain is trained on the declared red-team + dogfood capture (§5).
"""

from __future__ import annotations

from collections import defaultdict

from credence_governor_core.config import HARM
from credence_governor_core.safety import extract_safety
from credence_governor_core.training.build_harm_brain import build_coding, fold_benign_negatives
from credence_governor_core.training.fp_eval import BENIGN_CODING_CASES, benign_coding_calls

# The shipped coding-native harm 7-tuple; build_coding/extract_harm/config.HARM agree on order.
CTX_KEYS = HARM["feature_names"]
_SRC_I = CTX_KEYS.index("taint-source")

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


def test_coding_build_concentrates_harm_in_external_provenance():
    # The coding-native build (red-team n1 + curated benign n0, no capture): the injected
    # red-team attacks are web-sourced and carry harm; the own/none benign provenance
    # never carries the harm label.
    doc = build_coding()  # no capture path → deterministic (red-team + curated only)
    by_src: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for c in doc["contexts"]:
        by_src[c["ctx"][_SRC_I]][0] += c["n0"]
        by_src[c["ctx"][_SRC_I]][1] += c["n1"]
    # the injected attacks (web_fetch in history) are web-sourced and carry harm
    assert by_src["web"][1] > 0, "injected red-team attacks must be web-sourced harm"
    # own/none provenance is benign — the read-then-act negatives never flip to harm
    assert by_src["read-own"][1] == 0
    for ext in _EXTERNAL_SOURCES:
        n0, n1 = by_src[ext]
        if n0 + n1:
            assert n1 / (n0 + n1) >= 0.5, f"{ext} provenance should stay high-harm"


def test_coding_build_is_deterministic_without_capture():
    # No capture path → reproducible from the declared corpora alone (the capture half is
    # private growing dogfood and is NOT byte-reproducible by design; §5).
    import json
    a, b = build_coding(), build_coding()
    assert json.dumps(a, indent=4) == json.dumps(b, indent=4)
