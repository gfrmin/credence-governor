"""Manifest tests — the bundled data/bdsl/ declarations must parse, and every
declared feature/effector must have a registered extractor/implementation (the
fail-closed startup check)."""

import os

from credence_governor_core.features import extractors
from credence_governor_core.manifest import (
    parse_capabilities,
    read_capabilities,
    read_features,
    verify_effectors,
    verify_features,
)

_DATA = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "credence_governor_core",
    "data",
    "bdsl",
)

# The effectors the daemon renders (proceed/block/ask).
EFFECTOR_REGISTRY = {"ask": None, "proceed": None, "block": None}


def test_features_bdsl_declares_exactly_the_registered_extractors():
    decls = read_features(os.path.join(_DATA, "features.bdsl"))
    # Every declared feature has an extractor (fail-closed).
    verify_features(decls, extractors)
    # And the declared set matches the extractor set (no dead categories).
    assert {d.name for d in decls} == set(extractors.keys())


def test_capabilities_bdsl_effectors_have_implementations():
    decls = read_capabilities(os.path.join(_DATA, "capabilities.bdsl"))
    verify_effectors(decls, EFFECTOR_REGISTRY)
    assert {d.name for d in decls} == set(EFFECTOR_REGISTRY.keys())


def test_verify_features_fails_closed_on_missing_extractor():
    decls = read_features(os.path.join(_DATA, "features.bdsl"))
    try:
        verify_features(decls, {"tool-name": None})  # missing the rest
    except ValueError as e:
        assert "no extractor registered" in str(e)
    else:
        raise AssertionError("verify_features should have raised on a missing extractor")


def test_effector_parameters_parse():
    src = "(effector ask (parameters (text string)))\n(effector proceed (parameters))"
    decls = parse_capabilities(src)
    by_name = {d.name: d for d in decls}
    assert by_name["ask"].parameters[0].name == "text"
    assert by_name["ask"].parameters[0].type == "string"
    assert by_name["proceed"].parameters == []
