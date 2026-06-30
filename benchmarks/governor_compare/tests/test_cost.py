# Role: eval
"""Tests for the Phase 2 cost-axis routing comparison (synthetic grid — no API, no skin)."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "cost"))

import cost_compare as CC
import dataset as D
import oracle as O

MODELS = ["claude-haiku-4-5", "claude-sonnet-4-6", "claude-opus-4-6"]  # cheap → strong


def _cell(tid, model, passed, cost):
    return O.Cell(tid, model, passed, 100, 200, cost, 1.0)


# A: all pass; B: cheap fails / mid+strong pass; C: all fail.
GRID = {
    ("A", "claude-haiku-4-5"): _cell("A", "claude-haiku-4-5", True, 0.001),
    ("A", "claude-sonnet-4-6"): _cell("A", "claude-sonnet-4-6", True, 0.003),
    ("A", "claude-opus-4-6"): _cell("A", "claude-opus-4-6", True, 0.005),
    ("B", "claude-haiku-4-5"): _cell("B", "claude-haiku-4-5", False, 0.001),
    ("B", "claude-sonnet-4-6"): _cell("B", "claude-sonnet-4-6", True, 0.003),
    ("B", "claude-opus-4-6"): _cell("B", "claude-opus-4-6", True, 0.005),
    ("C", "claude-haiku-4-5"): _cell("C", "claude-haiku-4-5", False, 0.001),
    ("C", "claude-sonnet-4-6"): _cell("C", "claude-sonnet-4-6", False, 0.003),
    ("C", "claude-opus-4-6"): _cell("C", "claude-opus-4-6", False, 0.005),
}
TEST = ["A", "B", "C"]


def test_always_cheap_charges_cheap_cost_and_pass():
    r = CC.score("always-cheap", lambda t: MODELS[0], TEST, GRID, MODELS)
    assert r["pass_rate"] == round(1 / 3, 4)           # only A passes on haiku
    assert abs(r["total_cost"] - 0.003) < 1e-9         # 3 × $0.001


def test_clairvoyant_picks_cheapest_passing():
    def clair(tid):
        for m in MODELS:
            if GRID[(tid, m)].passed:
                return m
        return MODELS[0]
    r = CC.score("clairvoyant", clair, TEST, GRID, MODELS)
    # A→haiku(0.001), B→sonnet(0.003), C→none pass→haiku(0.001); pass A,B
    assert r["pass_rate"] == round(2 / 3, 4)
    assert abs(r["total_cost"] - 0.005) < 1e-9


def test_cascade_charges_cumulative_and_stops_at_first_pass():
    r = CC.score("cascade", lambda t: list(MODELS), TEST, GRID, MODELS)
    # A: haiku pass .001; B: haiku .001 + sonnet pass .003; C: all .001+.003+.005
    assert abs(r["total_cost"] - (0.001 + 0.004 + 0.009)) < 1e-9
    assert r["pass_rate"] == round(2 / 3, 4)


def test_difficulty_bins_partition_by_prompt_length():
    tasks = [D.CodingTask(f"T{i}", "x" * (i * 10 + 1), "f", "t") for i in range(9)]
    bins = CC.difficulty_bins(tasks, n_bins=3)
    assert set(bins.values()) <= {0, 1, 2}
    # the shortest prompt lands in the lowest bin, the longest in the highest
    assert bins["T0"] == 0 and bins["T8"] == 2


def test_train_bin_acc_is_learned_only_from_train_split():
    bins = {"A": 0, "B": 0, "C": 0}
    acc = CC._train_bin_acc(GRID, ["A", "B"], bins, MODELS, 1)
    # bin0 train = {A,B}: haiku passes A only → 0.5; opus passes both → 1.0
    assert acc[(0, 0)] == 0.5
    assert acc[(2, 0)] == 1.0
