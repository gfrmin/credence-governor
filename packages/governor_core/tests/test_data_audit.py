"""test_data_audit.py — hermetic tests of the data audit's pure core.

No live logs, no engines: collectors run against a fabricated mini data layout
under tmp_path. The two properties the plan pins: (1) the audit assigns NO
labels — no admissibility/label/good/bad key anywhere in the emitted dossier
structure; (2) the report is deterministic over a fixed layout."""

import json
import os

from credence_governor_core.training.data_audit import (
    LEDGER_CHANNELS,
    brain_counts_summary,
    build_dossiers,
    count_lines,
    dossiers_to_json,
    dossiers_to_markdown,
    observation_log_summary,
    parse_outcomes_distribution,
    reconcile,
    sample_jsonl_fields,
)


def test_count_lines_with_and_without_trailing_newline(tmp_path):
    p = tmp_path / "a.jsonl"
    p.write_bytes(b'{"x":1}\n{"x":2}\n')
    assert count_lines(str(p)) == 2
    p.write_bytes(b'{"x":1}\n{"x":2}')          # unterminated final record
    assert count_lines(str(p)) == 2
    p.write_bytes(b"")
    assert count_lines(str(p)) == 0


def test_sample_jsonl_fields_skips_malformed(tmp_path):
    p = tmp_path / "b.jsonl"
    p.write_text('{"a":1,"b":2}\nnot json\n{"c":3}\n')
    assert sample_jsonl_fields(str(p)) == ["a", "b", "c"]


def test_brain_counts_summary_totals():
    doc = {
        "corpus": "test@rev", "note": "n", "frozen": False,
        "contexts": [
            {"ctx": ["a"], "n1": 2, "n0": 1},
            {"ctx": ["b"], "n1": 3, "n0": 0},
        ],
    }
    s = brain_counts_summary(doc)
    assert s["contexts"] == 2 and s["n1_total"] == 5 and s["n0_total"] == 1
    assert "corpus" in s["metadata_keys"] and "contexts" not in s["metadata_keys"]
    assert s["self_description"]["corpus"] == "test@rev"


def test_observation_log_summary_tallies():
    recs = [
        {"event_type": "tool-proposed"},
        {"event_type": "decision", "action": "proceed"},
        {"event_type": "decision", "action": "ask"},
        {"event_type": "user-responded", "response": "yes"},
        {"event_type": "user-responded", "response": "no"},
        {"event_type": "user-responded", "response": "yes"},
    ]
    s = observation_log_summary(recs)
    assert s["events_by_type"] == {
        "decision": 2, "tool-proposed": 1, "user-responded": 3}
    assert s["decisions_by_action"] == {"ask": 1, "proceed": 1}
    assert s["responses"] == {"no": 1, "yes": 2}


def test_parse_outcomes_distribution():
    md = ("| Outcome | Calls | Share |\n|---|---|---|\n"
          "| accepted | 1798 | 61.0% |\n| reverted | 0 | 0.0% |\n"
          "| ambiguous | 1148 | 39.0% |\n")
    assert parse_outcomes_distribution(md) == {
        "accepted": 1798, "reverted": 0, "ambiguous": 1148}
    assert parse_outcomes_distribution("no table here") == {}


def _mini_layout(tmp_path):
    """A fabricated credence-governor checkout + home with tiny datasets."""
    root = tmp_path / "repo"
    home = tmp_path / "home"
    brain = root / "packages/governor_core/credence_governor_core/data/brain"
    bench = root / "benchmarks/governor_compare"
    live = home / ".credence-governor"
    for d in (brain, bench / "cost", live):
        os.makedirs(d)

    counts = {"corpus": "mini@0", "contexts": [{"ctx": ["x"], "n1": 4, "n0": 1}]}
    for name in ("warm_brain", "harm_brain", "tail_brain",
                 "routing_brain", "routing_latency"):
        (brain / f"{name}.counts.json").write_text(json.dumps(counts))

    (bench / ".cache_benign.jsonl").write_text(
        '{"cid":"cap-0","is_harm":false}\n{"cid":"cap-1","is_harm":false}\n')
    (bench / "OUTCOMES.md").write_text(
        "| accepted | 1 |\n| reverted | 0 |\n| ambiguous | 1 |\n")
    (bench / "cost/coding_grid.jsonl").write_text(
        '{"task_id":"t","passed":true,"cost":0.1}\n')
    (bench / "swebench_verified_sample.jsonl").write_text(
        '{"instance_id":"i","fail_to_pass":"[]"}\n')

    (live / "observations.jsonl").write_text(
        '{"event_type":"decision","action":"ask"}\n'
        '{"event_type":"user-responded","response":"yes"}\n')
    (live / "observations.pre-dogfood.jsonl").write_text("")
    (live / "observations.selfblock.jsonl").write_text("")
    (live / "raw_events.jsonl").write_text('{"event_id":"e1"}\n')
    return str(root), str(home)


def _all_keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _all_keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _all_keys(v)


def test_dossiers_assign_no_labels(tmp_path):
    root, home = _mini_layout(tmp_path)
    ds = build_dossiers(root, home=home)
    doc = json.loads(dossiers_to_json(ds, reconcile(ds)))
    forbidden = {"label", "labels", "admissible", "admissibility",
                 "good", "bad", "approve", "refuse", "is_harm"}
    keys = set(_all_keys(doc["dossiers"]))
    assert not (keys & forbidden), keys & forbidden
    # channel candidacy keys stay within the ledger's four channels
    for d in doc["dossiers"]:
        assert set(d["channel_candidacy"]) <= set(LEDGER_CHANNELS)


def test_audit_is_deterministic_over_fixed_layout(tmp_path):
    root, home = _mini_layout(tmp_path)
    one = dossiers_to_json(build_dossiers(root, home=home),
                           reconcile(build_dossiers(root, home=home)))
    two = dossiers_to_json(build_dossiers(root, home=home),
                           reconcile(build_dossiers(root, home=home)))
    assert one == two


def test_every_dossier_has_provenance_and_open_questions(tmp_path):
    root, home = _mini_layout(tmp_path)
    for d in build_dossiers(root, home=home):
        assert d.produced_by and d.selection and d.responder, d.name
        assert d.open_questions, d.name


def test_cache_benign_provenance_answered(tmp_path):
    root, home = _mini_layout(tmp_path)
    d = {x.name: x for x in build_dossiers(root, home=home)}[".cache_benign.jsonl"]
    assert "raw_events.jsonl" in d.produced_by
    assert "INHERITED FROM THE STREAM DEFINITION" in d.produced_by
    assert d.records == 2


def test_raw_events_not_counted_without_heavy(tmp_path):
    root, home = _mini_layout(tmp_path)
    by = {x.name: x for x in build_dossiers(root, home=home)}
    assert by["raw_events.jsonl"].records == "not counted (pass --heavy)"
    by_heavy = {x.name: x for x in build_dossiers(root, home=home, heavy=True)}
    assert by_heavy["raw_events.jsonl"].records == 1


def test_reconcile_marks_matches_minimums_and_misses(tmp_path):
    root, home = _mini_layout(tmp_path)
    ds = build_dossiers(root, home=home)
    rows = {(r["name"], r["quantity"]): r for r in reconcile(ds)}
    # mini layout has 1 context where the inventory expects 118 -> a fact, not a crash
    assert rows[("warm_brain.counts.json", "contexts")]["match"] == "NO"
    # in-code corpora are the real ones even under the mini layout
    assert rows[("RED_TEAM_CASES", "records")]["match"] == "yes"
    assert rows[("BENIGN_CODING_CASES", "records")]["match"] == "yes"
    # live logs: below the recorded minimum in the mini layout
    assert rows[("observations.jsonl", "records")]["match"] == "BELOW minimum"
    # raw capture not counted by default
    assert rows[("raw_events.jsonl", "records")]["match"] == "not counted"


def test_markdown_renders_every_dossier_and_disclaimer(tmp_path):
    root, home = _mini_layout(tmp_path)
    ds = build_dossiers(root, home=home)
    md = dossiers_to_markdown(ds, reconcile(ds))
    for d in ds:
        assert f"## {d.name}" in md
    assert "assigns no labels" in md
    assert "open questions for the author's label rulings" in md
    assert "| source | quantity | expected | observed | match |" in md


def test_missing_files_reported_not_fatal(tmp_path):
    root = tmp_path / "empty-repo"
    home = tmp_path / "empty-home"
    os.makedirs(root)
    os.makedirs(home)
    ds = build_dossiers(str(root), home=str(home))
    assert any(not d.exists for d in ds)
    # rendering still works
    assert "(MISSING)" in dossiers_to_markdown(ds, reconcile(ds))
