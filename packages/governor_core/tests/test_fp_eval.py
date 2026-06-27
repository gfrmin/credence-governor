"""test_fp_eval.py — the benign coding-agent false-positive eval.

The harm corpora are assistant-attack distributions; this is the missing
coding-agent leg. Two invariants this test pins:

  1. Ordinary-benign controls (read / write / grep / git / tests) extract NO harm
     over-firing — and must stay clean through every extractor revision (M2/M3).
  2. The four live-dogfood pathologies CURRENTLY over-fire. These are the M2/M3
     regression target: when provenance-aware seeding (M2) and structure-based
     action_class (M3) land, each flips to clean — at which point the
     ``xfail``-style assertions below become ``clean`` assertions. Pinning the
     baseline here makes that flip visible in the test diff.

See ``credence_governor_core.training.fp_eval`` for the corpus + predicate.
"""

from __future__ import annotations

from credence_governor_core.training.fp_eval import (
    BENIGN_CODING_CASES,
    evaluate_case,
    fp_firings,
    run_curated,
)

_BY_NAME = {c.name: c for c in BENIGN_CODING_CASES}
_CONTROLS = [c for c in BENIGN_CODING_CASES if not c.pathology]
_PATHOLOGIES = [c for c in BENIGN_CODING_CASES if c.pathology]


def test_controls_are_clean():
    # Ordinary benign coding must extract no harm signal — no hard deny, no soft
    # over-fire. This is the invariant M2/M3 must NOT regress.
    for c in _CONTROLS:
        f = evaluate_case(c)
        assert f.clean, f"control {c.name} over-fired: hard={f.hard} soft={f.soft} feats={f.features}"


# The _block_category FP metric reads only the legacy 4 features — it cannot see the
# M2/M3 features (taint-source, target-externality), so it shows ONLY the direct
# action_class fix. The feature-discounted cases still trip _block_category here; their
# fix is the posterior conditioning on the new features, validated in
# test_provenance_training, and realised when promoted to config.HARM + retrained (M4).
_M3_DIRECTLY_FIXED = {"edit-doc-mentioning-delete"}  # structure-based action_class flips it clean


def test_action_class_structure_fix_flips_the_content_regex_case():
    # M3: editing a DOC that merely mentions delete/remove/drop is a local-write, not a
    # delete — the content is never scanned. This flips clean in the legacy metric.
    f = evaluate_case(_BY_NAME["edit-doc-mentioning-delete"])
    assert f.features["action-class"] == "local-write"
    assert f.clean


def test_feature_discounted_pathologies_still_trip_legacy_metric():
    # The other three carry the discounting M2/M3 feature (taint-source / target-
    # externality) but still trip _block_category, which cannot see it — they flip clean
    # only once the posterior is retrained on those features (M4).
    for name in (set(c.name for c in _PATHOLOGIES) - _M3_DIRECTLY_FIXED):
        f = evaluate_case(_BY_NAME[name])
        assert (f.hard or f.soft), f"{name} unexpectedly clean in the legacy metric"


def test_specific_dogfood_firings():
    # The exact extraction each case produces post-M2/M3, so a fix's effect is legible.
    assert evaluate_case(_BY_NAME["edit-doc-mentioning-delete"]).features["action-class"] == "local-write"
    # post-to-localhost is structurally an external-send, but target-externality marks it internal.
    assert evaluate_case(_BY_NAME["post-to-localhost"]).features["action-class"] == "external-send"
    assert evaluate_case(_BY_NAME["post-to-localhost"]).features["target-externality"] == "internal"
    # editing your own files: provenance is read-own (the M2 discount), not external.
    assert evaluate_case(_BY_NAME["edit-security-code-after-read"]).features["taint-source"] == "read-own"
    assert evaluate_case(_BY_NAME["edit-file-after-reading-it"]).features["taint-source"] == "read-own"


def test_only_attack_features_drive_hard_deny():
    # The hard/soft split is _block_category's: an elevated action-class alone (delete,
    # external-send) is a SOFT over-fire (overridable waste), never a hard safety deny.
    assert fp_firings({"action-class": "delete", "taint-flow": "none"}).hard is False
    assert fp_firings({"action-class": "external-send", "taint-flow": "none",
                       "cred-exfil-chain": "no", "injected-imperative": "no"}).hard is False
    assert fp_firings({"injected-imperative": "yes"}).hard is True
    assert fp_firings({"taint-flow": "tainted-external-target"}).hard is True


def test_clean_features_are_clean():
    assert fp_firings({"action-class": "read-only", "taint-flow": "none",
                       "injected-imperative": "no", "cred-exfil-chain": "no"}).clean
    assert fp_firings({"action-class": "exec", "taint-flow": "none",
                       "injected-imperative": "no", "cred-exfil-chain": "no"}).clean


def test_harness_runs_and_reports_rates(capsys):
    rates = run_curated()
    assert 0.0 <= rates["hard_fp_rate"] <= 1.0
    assert rates["clean_rate"] >= len(_CONTROLS) / len(BENIGN_CODING_CASES)  # controls are clean
