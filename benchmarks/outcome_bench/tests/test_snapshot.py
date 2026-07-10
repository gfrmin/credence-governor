"""test_snapshot.py — the committed outcome_bench_results.json claims (the
drift guard that keeps OUTCOME_BENCH.md honest). These pin the STRUCTURAL
findings of the registered reading — they must survive regeneration on a
grown log unless the finding itself changes, which is exactly when a human
should look."""

import json
import math
import os

import pytest

RESULTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "outcome_bench_results.json")


@pytest.fixture(scope="module")
def results():
    if not os.path.exists(RESULTS):
        pytest.skip("no committed results JSON yet (generate with bench.py)")
    with open(RESULTS, encoding="utf-8") as f:
        return json.load(f)


def test_manifest_pins_the_reading(results):
    m = results["manifest"]
    assert m["sha256"] and m["n_lines"] > 0 and m["path"].endswith(".jsonl")


def test_corpus_shape_and_the_zero_justified_blocks_finding(results):
    c = results["corpus"]
    # rows sum to the decision count
    assert sum(sum(v.values()) for v in c["per_action"].values()) == c["decisions"]
    # the headline findings of the shadow-counterfactual reading
    assert c["outcome_justified_blocks"] == 0
    assert c["would_block_rate"] >= 0.15
    assert c["decisive"] >= 15000


def test_incumbent_scores(results):
    e = results["engines"]
    assert e["ORACLE"]["mean_loss"] == 0.0
    assert e["incumbent"]["mean_loss"] > e["UNGOVERNED"]["mean_loss"]
    # catch 0 => blocking never pays: the infinite break-even
    assert e["incumbent"]["catch_on_reverted"] == 0.0
    assert e["incumbent"].get("breakeven_pi_infinite") is True
    # bounds bracket the point estimate
    lo, hi = e["incumbent"]["mean_loss_bounds"]
    assert lo <= e["incumbent"]["mean_loss"] <= hi
    # the per-category split: safety-category FBR exceeds waste FBR
    fbr = e["incumbent"]["fbr_by_category"]
    assert fbr["safety"]["fbr"] > fbr["waste"]["fbr"] > 0


def test_challenger_scored_on_intersection(results):
    ch = results.get("challenger")
    if not ch:
        pytest.skip("no challenger replay committed yet")
    assert ch["scored_intersection"] > 30000
    assert "membrane-table@1" in results["engines"]
    mem = results["engines"]["membrane-table@1"]
    assert mem["n_decisive"] > 14000
    assert mem["mean_loss"] is not None and not math.isnan(mem["mean_loss"])


def test_bars_registered_at_rd14_close(results):
    bars = results["bars"]
    assert bars["values"] == {"waste": {"fbr_bar": 0.0005}}
    assert bars["n_min"] == 1000
    assert bars["window_days"] == 30
    assert "rd14-close" in bars["registered"]
    # the incumbent FAILS the waste bar (6.5% vs 0.05%); safety has no bar
    assert bars["clears"]["incumbent"] == {"waste": False, "safety": None}
    # the all-ask membrane clears vacuously (it never blocks)
    assert bars["clears"]["membrane-table@1"]["waste"] is True
