"""data_audit.py — descriptive dossiers of every dataset the governor knows about.

AUDIT ONLY. This module assigns NO labels and renders NO admissibility verdicts:
whether a source may enter a learning channel — and as what — is a ruling that
belongs to the author (the HOSTS_D_PACK register), not to this code. Each dossier
DESCRIBES a source in the utility doctrine's own terms:

  * provenance chain — who/what produced each record (human verdict, fixture
    constructed for the corpus, harness auto-outcome, machine detector,
    uncurated capture, derived artifact);
  * channel candidacy — which of the four identifiability-ledger channels the
    source COULD feed (verdict / outcome / comparison / deference), and what
    responder sits between the record and the truth;
  * measured units present ($, tokens, retries, latency, pass-fail);
  * selection process — how records came to be in the set (policy-filtered
    capture? benchmark-generated? authored?).

Every dossier ends with the open questions the source poses for the author's
label rulings. The report is deterministic over the committed datasets; live
logs are described as live (their numbers move between runs by design).

Run:

    uv run --project packages/governor_core \\
        python -m credence_governor_core.training.data_audit [--heavy] [--out-dir DIR]

--heavy additionally line-counts the ~56 GB raw capture (minutes of IO);
without it that one count is reported as "not counted".
"""

from __future__ import annotations

import argparse
import json
import os
import re
from collections.abc import Iterable, Iterator
from dataclasses import asdict, dataclass, field
from typing import Any

# The four channels of the identifiability ledger (HOSTS_D_PACK §1). Channel
# candidacy is a STRUCTURAL observation ("this source could feed that channel"),
# not an admission ruling.
LEDGER_CHANNELS = ("verdict", "outcome", "comparison", "deference")

# ---------------------------------------------------------------------------
# pure helpers (hermetically tested)
# ---------------------------------------------------------------------------


def count_lines(path: str) -> int:
    """Newline count by buffered binary read — streams, never loads the file
    (the raw capture is ~56 GB). A final unterminated line is still a record."""
    n = 0
    last = b"\n"
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            n += chunk.count(b"\n")
            last = chunk[-1:]
    return n + (0 if last == b"\n" else 1)


def sample_jsonl_fields(path: str, k: int = 25) -> list[str]:
    """The union of top-level field names over the first k parseable records —
    a schema sketch, not a validation. Malformed lines are skipped (live logs
    may carry a partial tail)."""
    fields: set[str] = set()
    seen = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            if seen >= k:
                break
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(rec, dict):
                fields.update(rec.keys())
                seen += 1
    return sorted(fields)


def brain_counts_summary(doc: dict[str, Any]) -> dict[str, Any]:
    """Totals of a *.counts.json brain file: context count and the sums of the
    per-context n1/n0 tallies, plus the file's own metadata keys (the file's
    self-description — reported verbatim, never reinterpreted)."""
    contexts = doc.get("contexts") or []
    return {
        "contexts": len(contexts),
        "n1_total": sum(int(c.get("n1", 0)) for c in contexts),
        "n0_total": sum(int(c.get("n0", 0)) for c in contexts),
        "metadata_keys": sorted(k for k in doc if k != "contexts"),
        "self_description": {
            k: doc[k]
            for k in ("corpus", "note", "trained_at", "frozen")
            if k in doc
        },
    }


def observation_log_summary(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Event-type / decision-action / response tallies over an observation log
    stream. Pure over an iterable so the 52k-line live log streams through."""
    by_type: dict[str, int] = {}
    by_action: dict[str, int] = {}
    by_response: dict[str, int] = {}
    for rec in records:
        et = str(rec.get("event_type", "?"))
        by_type[et] = by_type.get(et, 0) + 1
        if et == "decision":
            a = str(rec.get("action", "?"))
            by_action[a] = by_action.get(a, 0) + 1
        elif et == "user-responded":
            r = str(rec.get("response", "?"))
            by_response[r] = by_response.get(r, 0) + 1
    return {
        "events_by_type": dict(sorted(by_type.items())),
        "decisions_by_action": dict(sorted(by_action.items())),
        "responses": dict(sorted(by_response.items())),
    }


def iter_jsonl(path: str) -> Iterator[dict[str, Any]]:
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(rec, dict):
                yield rec


def parse_outcomes_distribution(md_text: str) -> dict[str, int]:
    """The accepted/reverted/ambiguous counts from OUTCOMES.md's first table —
    tolerant of absence (returns {} if the table is not found)."""
    out: dict[str, int] = {}
    for name in ("accepted", "reverted", "ambiguous"):
        m = re.search(rf"^\|\s*{name}\s*\|\s*(\d+)\s*\|", md_text, re.MULTILINE)
        if m:
            out[name] = int(m.group(1))
    return out


# ---------------------------------------------------------------------------
# the dossier
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Dossier:
    """One source, described. No field of this record is a label or a verdict;
    `channel_candidacy` notes structural possibility only."""

    name: str
    path: str
    exists: bool
    bytes: int | None
    records: int | str | None       # count, or a note like "not counted (--heavy)"
    record_unit: str
    schema_fields: list[str]
    produced_by: str                # the provenance chain, as specifically as known
    selection: str                  # how records came to be in the set
    responder: str                  # what sits between record and truth
    channel_candidacy: dict[str, str]   # ledger channel -> structural note
    units: list[str]                # measured units present in the records
    open_questions: list[str]       # what the author must rule before any label
    notes: list[str] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)


def _stat(path: str) -> tuple[bool, int | None]:
    try:
        return True, os.stat(path).st_size
    except OSError:
        return False, None


# ---------------------------------------------------------------------------
# collectors — one per source; all take explicit paths (hermetic testing)
# ---------------------------------------------------------------------------


def collect_brain_counts(name: str, path: str, produced_by: str, selection: str,
                         responder: str, candidacy: dict[str, str],
                         open_questions: list[str],
                         notes: list[str] | None = None) -> Dossier:
    exists, nbytes = _stat(path)
    summary: dict[str, Any] = {}
    fields_: list[str] = []
    records: int | None = None
    if exists:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
        summary = brain_counts_summary(doc)
        fields_ = summary.pop("metadata_keys")
        records = summary["contexts"]
    return Dossier(
        name=name, path=path, exists=exists, bytes=nbytes,
        records=records, record_unit="contexts",
        schema_fields=fields_, produced_by=produced_by, selection=selection,
        responder=responder, channel_candidacy=candidacy,
        units=["counts (n1/n0 tallies)"],
        open_questions=open_questions, notes=notes or [], summary=summary)


def collect_jsonl(name: str, path: str, record_unit: str, produced_by: str,
                  selection: str, responder: str, candidacy: dict[str, str],
                  units: list[str], open_questions: list[str],
                  notes: list[str] | None = None,
                  count: bool = True) -> Dossier:
    exists, nbytes = _stat(path)
    records: int | str | None = None
    fields_: list[str] = []
    if exists:
        fields_ = sample_jsonl_fields(path)
        records = count_lines(path) if count else "not counted (pass --heavy)"
    return Dossier(
        name=name, path=path, exists=exists, bytes=nbytes,
        records=records, record_unit=record_unit,
        schema_fields=fields_, produced_by=produced_by, selection=selection,
        responder=responder, channel_candidacy=candidacy, units=units,
        open_questions=open_questions, notes=notes or [])


def collect_in_code_corpus(name: str, count: int, module: str, produced_by: str,
                           responder: str, candidacy: dict[str, str],
                           open_questions: list[str]) -> Dossier:
    return Dossier(
        name=name, path=module, exists=True, bytes=None,
        records=count, record_unit="cases",
        schema_fields=["name", "event", "session", "note"],
        produced_by=produced_by,
        selection="authored: each case exists because its author wrote it into "
                  "the corpus (coverage reflects the author's threat/pathology model)",
        responder=responder, channel_candidacy=candidacy,
        units=[], open_questions=open_questions)


def collect_observation_log(name: str, path: str, produced_by: str,
                            open_questions: list[str],
                            notes: list[str] | None = None) -> Dossier:
    exists, nbytes = _stat(path)
    summary: dict[str, Any] = {}
    fields_: list[str] = []
    records: int | None = None
    if exists:
        summary = observation_log_summary(iter_jsonl(path))
        fields_ = sample_jsonl_fields(path)
        records = sum(summary["events_by_type"].values())
    return Dossier(
        name=name, path=path, exists=exists, bytes=nbytes,
        records=records, record_unit="events",
        schema_fields=fields_, produced_by=produced_by,
        selection="live append-only log of the deployed daemon's own traffic — "
                  "policy-selected by construction (records what the deployed "
                  "governor was asked and did)",
        responder="decisions: the deployed policy itself; user-responded events: "
                  "the in-the-moment owner via the /feedback endpoint (Claude Code "
                  "has no approval-resolution callback, so most overrides go "
                  "unrecorded)",
        channel_candidacy={
            "verdict": "user-responded events are owner verdicts (sparse; see summary)",
            "deference": "decision events record the policy's ask/block/proceed "
                         "choices — deference *behavior*, not ground truth",
        },
        units=["timestamps"], open_questions=open_questions,
        notes=(notes or []) + ["LIVE file: counts move between runs by design"],
        summary=summary)


# ---------------------------------------------------------------------------
# the audit — every known source, described
# ---------------------------------------------------------------------------

def build_dossiers(repo_root: str, home: str | None = None,
                   heavy: bool = False) -> list[Dossier]:
    """Every dataset the governor knows about, described. `repo_root` is the
    credence-governor checkout; `home` overrides ~ (hermetic tests)."""
    home = home or os.path.expanduser("~")
    core = os.path.join(repo_root, "packages/governor_core/credence_governor_core")
    brain = os.path.join(core, "data/brain")
    bench = os.path.join(repo_root, "benchmarks/governor_compare")
    live = os.path.join(home, ".credence-governor")

    ds: list[Dossier] = []

    # -- committed brains (data/brain/*.counts.json) ------------------------
    ds.append(collect_brain_counts(
        "warm_brain.counts.json", os.path.join(brain, "warm_brain.counts.json"),
        produced_by="ClawsBench benchmark harness (the file's own `corpus` key names "
                    "the revision): n1 = harness auto-approvals of governed calls, "
                    "n0 = the loop-repetition detector's denials — both MACHINE "
                    "signals; no human issued any of these tallies",
        selection="benchmark-generated traffic (ClawsBench episodes), aggregated "
                  "per feature-context",
        responder="the benchmark harness's auto-approve rule and the repetition "
                  "detector — not an owner",
        candidacy={
            "verdict": "structurally verdict-SHAPED (per-context approve/deny "
                       "tallies) but machine-issued; whether machine signals may "
                       "enter the verdict channel at all is an author ruling",
        },
        open_questions=[
            "May harness auto-approvals stand in for owner approvals, at what "
            "discount, if at all?",
            "Are loop-denials a waste signal (their own stream) rather than a "
            "verdict at all?",
        ]))

    ds.append(collect_brain_counts(
        "harm_brain.counts.json", os.path.join(brain, "harm_brain.counts.json"),
        produced_by="mixed per the file's own `corpus` key: declared red-team "
                    "fixtures (n1), curated benign cases, and a captured-dogfood "
                    "snapshot folded as n0 (the file's metadata records "
                    "n_benign_captured; that fold predates the capture's current "
                    "size — a stale snapshot)",
        selection="three different selection processes folded into one table "
                  "(authored attacks; curated benign; policy-filtered capture)",
        responder="none for the fixtures (labels by construction); the capture "
                  "fold inherited benign-by-assumption",
        candidacy={
            "verdict": "fixture rows are by-construction cases, not owner verdicts",
            "outcome": "none recorded",
        },
        open_questions=[
            "The captured-benign fold predates outcome-grounding — should any "
            "future fold require grounded (accepted) status first?",
            "Do by-construction fixtures enter learning as evidence or remain "
            "eval-only?",
        ]))

    ds.append(collect_brain_counts(
        "tail_brain.counts.json", os.path.join(brain, "tail_brain.counts.json"),
        produced_by="the same ClawsBench harness run as warm_brain, re-keyed as "
                    "stop/continue tallies",
        selection="benchmark-generated (mirror of warm_brain)",
        responder="the benchmark harness (machine)",
        candidacy={"verdict": "same machine-signal question as warm_brain"},
        open_questions=["Stands or falls with the warm_brain ruling"]))

    for rname in ("routing_brain.counts.json", "routing_latency.counts.json"):
        ds.append(collect_brain_counts(
            rname, os.path.join(brain, rname),
            produced_by="declared per-model roster priors (no per-context counts "
                        "of real events)",
            selection="authored configuration",
            responder="none — these are priors, not records",
            candidacy={},
            open_questions=["Routing stays on the incumbent (named successor); "
                            "out of D's scope"],
            notes=["a prior declaration, not a dataset of events"]))

    # -- in-code corpora ----------------------------------------------------
    try:
        from .red_team import RED_TEAM_CASES
        n_red = len(RED_TEAM_CASES)
    except Exception:  # pragma: no cover — import always works in-repo
        n_red = -1
    try:
        from .fp_eval import BENIGN_CODING_CASES
        n_fp = len(BENIGN_CODING_CASES)
    except Exception:  # pragma: no cover
        n_fp = -1

    ds.append(collect_in_code_corpus(
        "RED_TEAM_CASES", n_red,
        "credence_governor_core/training/red_team.py",
        produced_by="hand-authored attack fixtures, each with a declared "
                    "threat_class and injected flag — synthetic by construction, "
                    "never captured",
        responder="none: the case IS its own ground truth (constructed to be an "
                  "attack)",
        candidacy={
            "outcome": "by-construction bad outcomes — but synthetic: whether "
                       "constructed cases feed the outcome channel or stay "
                       "eval-only is an author ruling",
        },
        open_questions=[
            "Evidence or eval-only?",
            "If evidence: at what weight relative to captured events (20 authored "
            "cases vs tens of thousands of real calls)?",
        ]))

    ds.append(collect_in_code_corpus(
        "BENIGN_CODING_CASES", n_fp,
        "credence_governor_core/training/fp_eval.py",
        produced_by="hand-authored benign fixtures (false-positive eval controls), "
                    "each with a declared pathology note",
        responder="none: constructed to be benign",
        candidacy={
            "outcome": "by-construction wanted-work — same constructed-case "
                       "question as RED_TEAM_CASES",
        },
        open_questions=["Same rulings as RED_TEAM_CASES"]))

    # -- retired corpus -----------------------------------------------------
    at = os.path.join(repo_root, "packages/governor_core/data_corpora/atbench_claw")
    ds.append(collect_jsonl(
        "atbench_claw/events.jsonl", os.path.join(at, "events.jsonl"),
        record_unit="events",
        produced_by="derived from the public ATBench/AgentDojo trajectory set "
                    "(test.json alongside) by replay; carries that corpus's own "
                    "per-trajectory safe/unsafe designations, projected to calls",
        selection="public benchmark's trajectory selection — assistant-shaped "
                  "traffic, RETIRED for this reason (feature mismatch with the "
                  "coding-native deployment)",
        responder="the public corpus's original annotators (provenance chain not "
                  "reconstructable from here)",
        candidacy={
            "outcome": "carries third-party designations of unsafe trajectories; "
                       "retired status and provenance opacity are the questions",
        },
        units=["turn_tokens", "turn_cost_usd"],
        open_questions=["Retired stays retired? (recommended in the pack; the "
                        "author confirms or reverses)"],
        notes=["RETIRED per the harm_brain corpus note"]))

    # -- benchmark-side datasets ---------------------------------------------
    ds.append(collect_jsonl(
        ".cache_benign.jsonl", os.path.join(bench, ".cache_benign.jsonl"),
        record_unit="feature records",
        produced_by="cache.py build_cache -> streams.benign_capture over the raw "
                    "capture (~/.credence-governor/raw_events.jsonl): the daemon's "
                    "exact feature projection, extracted once per call. Its "
                    "is_harm=False field is INHERITED FROM THE STREAM DEFINITION "
                    "(streams.py: 'benign-by-assumption real dev work'), not from "
                    "any human or outcome — the provenance answer the audit was "
                    "asked for",
        selection="policy-selected twice: the capture records what the deployed "
                  "governor's environment produced, and load_capture drops "
                  "truncated/duplicate records",
        responder="an assumption (the stream definition), later PARTIALLY "
                  "grounded by outcomes.py (see outcome-grounding dossier)",
        candidacy={
            "outcome": "the grounding replay attaches accepted/reverted/ambiguous "
                       "to exactly these records — candidacy runs through that "
                       "grounding, not through the inherited assumption",
        },
        units=[],
        open_questions=[
            "Does grounded-accepted suffice for the outcome channel, or is "
            "acceptance-without-revert too weak a signal of 'wanted'?",
            "The corpus-hygiene caveat (the capture contains this safety "
            "system's own synthetic attack fixtures as traffic): filter how?",
        ]))

    out_md = os.path.join(bench, "OUTCOMES.md")
    exists, nbytes = _stat(out_md)
    dist: dict[str, int] = {}
    if exists:
        with open(out_md, encoding="utf-8") as f:
            dist = parse_outcomes_distribution(f.read())
    ds.append(Dossier(
        name="outcome-grounding (outcomes.py + OUTCOMES.md)",
        path=out_md, exists=exists, bytes=nbytes,
        records=sum(dist.values()) or None, record_unit="grounded calls",
        schema_fields=sorted(dist.keys()),
        produced_by="structural session replay (outcomes.py): for each cached "
                    "call, what the developer's session DID with it afterwards — "
                    "accepted (kept working past it), reverted (explicitly undone), "
                    "ambiguous (unobserved tail). No LLM, no trust in any logged "
                    "decision",
        selection="exactly the .cache_benign.jsonl records (same filters)",
        responder="the developer's own subsequent actions — the one existing "
                  "signal with NO responder model between record and truth",
        channel_candidacy={
            "outcome": "the repo's one existing responder-free outcome extraction; "
                       "its distribution is in summary",
            "deference": "reverts of governor-permitted calls would be deference-"
                         "relevant; none observed in the current run",
        },
        units=["accepted/reverted/ambiguous (categorical outcome)"],
        open_questions=[
            "Is 'accepted' (no undo observed) strong enough to count as a good "
            "outcome, or only 'reverted' as a bad one?",
            "Ambiguous calls (unobserved tails) stay set aside — confirm?",
            "Which further observables join the outcome set (test results, "
            "session completion, spend)?",
        ],
        summary={"distribution": dist}))

    ds.append(collect_jsonl(
        "cost/coding_grid.jsonl", os.path.join(bench, "cost/coding_grid.jsonl"),
        record_unit="task runs",
        produced_by="benchmark harness runs of coding tasks per model: pass/fail "
                    "plus measured tokens, dollars, wall-clock",
        selection="benchmark task set (HumanEval-style), not deployment traffic",
        responder="the task's own test suite (machine, but objective pass/fail)",
        candidacy={
            "outcome": "measured-unit outcomes ($ + pass/fail) — the commensurate-"
                       "units exemplar; benchmark provenance is the question",
        },
        units=["cost ($)", "in_tokens/out_tokens", "wall_s", "passed (bool)"],
        open_questions=["Benchmark outcomes as calibration for the accounting "
                        "layer, or real-traffic outcomes only?"]))

    ds.append(collect_jsonl(
        "swebench_verified_sample.jsonl",
        os.path.join(bench, "swebench_verified_sample.jsonl"),
        record_unit="instances",
        produced_by="a sample of SWE-bench Verified (public benchmark; "
                    "fail_to_pass test lists per instance)",
        selection="public benchmark sample",
        responder="upstream benchmark's verified test suites",
        candidacy={"outcome": "same benchmark-provenance question as coding_grid"},
        units=["fail_to_pass (test outcomes)"],
        open_questions=["Same ruling as coding_grid"]))

    # -- live logs ------------------------------------------------------------
    ds.append(collect_observation_log(
        "observations.jsonl", os.path.join(live, "observations.jsonl"),
        produced_by="the deployed daemon (Claude Code adapter): tool-proposed / "
                    "decision / user-responded events, appended live",
        open_questions=[
            "The recorded owner verdicts are extremely sparse relative to "
            "decisions — seed the verdict channel from them at all, or wait for "
            "richer capture?",
            "Enable the openclaw adapter's resolution/latency capture so verdicts "
            "accrue with timestamps? (data-roadmap item)",
        ]))

    ds.append(collect_observation_log(
        "observations.pre-dogfood.jsonl",
        os.path.join(live, "observations.pre-dogfood.jsonl"),
        produced_by="a pre-dogfood test session (its user-responded events were "
                    "issued against a self-block test, not organic traffic)",
        open_questions=["Test-session verdicts: evidence or artifact?"]))

    ds.append(collect_observation_log(
        "observations.selfblock.jsonl",
        os.path.join(live, "observations.selfblock.jsonl"),
        produced_by="a self-block test session",
        open_questions=["Same as pre-dogfood"]))

    ds.append(collect_jsonl(
        "raw_events.jsonl", os.path.join(live, "raw_events.jsonl"),
        record_unit="captured calls",
        produced_by="the daemon's opt-in raw capture: full (tool_name, input, "
                    "session transcript) per governed call — real Claude Code "
                    "traffic, unlabeled",
        selection="policy-selected (what the deployed governor's environment "
                  "produced) and capture-window-selected; contains this safety "
                  "system's own development traffic including synthetic attack "
                  "fixtures authored as tests",
        responder="none recorded — the capture carries no verdicts and no "
                  "outcomes; outcome-grounding replays CAN be computed from it "
                  "(outcomes.py does)",
        candidacy={
            "outcome": "via structural replay (outcomes.py) only",
            "verdict": "none present",
        },
        units=["timestamps"],
        open_questions=[
            "Roles besides context-distribution and active-labeling pool?",
            "Active-labeling: rank by context-frequency x decision-sensitivity "
            "(the wire's p1/entropy) — confirm as the roadmap item?",
        ],
        notes=["~56 GB; LIVE file", "line count only under --heavy"],
        count=heavy))

    # -- predecessor product --------------------------------------------------
    ds.append(collect_jsonl(
        "credence-pi observations.jsonl",
        os.path.join(home, ".credence-pi/observations.jsonl"),
        record_unit="events",
        produced_by="a different, predecessor product (credence-pi routing/cost "
                    "telemetry; its own schema)",
        selection="that product's deployment window",
        responder="n/a — different decision surface",
        candidacy={},
        units=["turn-cost"],
        open_questions=["Out of scope for the governor's channels — confirm?"],
        notes=["described for completeness; not a governor dataset"]))

    return ds


# ---------------------------------------------------------------------------
# reconciliation against the 2026-07-08 inventory
# ---------------------------------------------------------------------------

# Expected values from the exploration inventory (2026-07-08). Live-log entries
# are minimums (the logs grow); committed datasets should match exactly.
EXPECTED: list[dict[str, Any]] = [
    {"name": "warm_brain.counts.json", "quantity": "contexts", "expected": 118},
    {"name": "warm_brain.counts.json", "quantity": "n1_total", "expected": 38958},
    {"name": "warm_brain.counts.json", "quantity": "n0_total", "expected": 356},
    {"name": "harm_brain.counts.json", "quantity": "contexts", "expected": 113},
    {"name": "harm_brain.counts.json", "quantity": "n1_total", "expected": 20},
    {"name": "harm_brain.counts.json", "quantity": "n0_total", "expected": 1812},
    {"name": "tail_brain.counts.json", "quantity": "contexts", "expected": 118},
    {"name": "RED_TEAM_CASES", "quantity": "records", "expected": 20},
    {"name": "BENIGN_CODING_CASES", "quantity": "records", "expected": 9},
    {"name": ".cache_benign.jsonl", "quantity": "records", "expected": 2946},
    {"name": "atbench_claw/events.jsonl", "quantity": "records", "expected": 2634},
    {"name": "cost/coding_grid.jsonl", "quantity": "records", "expected": 492},
    {"name": "swebench_verified_sample.jsonl", "quantity": "records", "expected": 30},
    {"name": "observations.jsonl", "quantity": "records",
     "expected": 52324, "minimum": True},
    # The exploration inventory estimated ~89.8k from a sampled average record
    # size (625 KB/rec); the first --heavy count measured 25,095 (records carry
    # full session transcripts, which GROW within a session, so late records
    # run ~2.3 MB). The measurement corrected the estimate — recorded here.
    {"name": "raw_events.jsonl", "quantity": "records",
     "expected": 25095, "minimum": True},
]


def _observed(d: Dossier, quantity: str) -> Any:
    if quantity == "records":
        return d.records
    return d.summary.get(quantity)


def reconcile(dossiers: list[Dossier],
              expected: list[dict[str, Any]] = EXPECTED) -> list[dict[str, Any]]:
    """Expected-vs-observed over the inventory's counts. Purely descriptive:
    a mismatch is a fact to explain, not a failure."""
    by_name = {d.name: d for d in dossiers}
    rows = []
    for e in expected:
        d = by_name.get(e["name"])
        obs = _observed(d, e["quantity"]) if d else None
        if not isinstance(obs, int):
            match = "not counted"
        elif e.get("minimum"):
            match = "yes (>= expected; live)" if obs >= e["expected"] else "BELOW minimum"
        else:
            match = "yes" if obs == e["expected"] else "NO"
        rows.append({"name": e["name"], "quantity": e["quantity"],
                     "expected": e["expected"], "observed": obs, "match": match})
    return rows


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------


def dossiers_to_json(dossiers: list[Dossier],
                     recon: list[dict[str, Any]]) -> str:
    doc = {
        "what": "descriptive dataset dossiers — no labels, no admissibility "
                "verdicts; label rulings are the author's (HOSTS_D_PACK register)",
        "ledger_channels": list(LEDGER_CHANNELS),
        "dossiers": [asdict(d) for d in sorted(dossiers, key=lambda d: d.name)],
        "reconciliation": recon,
    }
    return json.dumps(doc, indent=2, sort_keys=True)


def dossiers_to_markdown(dossiers: list[Dossier],
                         recon: list[dict[str, Any]]) -> str:
    L: list[str] = []
    L.append("# Data audit — descriptive dossiers (no labels assigned)")
    L.append("")
    L.append("_Every dataset the governor knows about, described in the utility "
             "doctrine's terms: provenance chain, ledger-channel candidacy "
             "(verdict / outcome / comparison / deference), responder between "
             "record and truth, measured units, selection process. **This audit "
             "assigns no labels and admits nothing into any channel** — those are "
             "the author's rulings; each dossier ends with the open questions it "
             "poses._")
    L.append("")
    for d in sorted(dossiers, key=lambda d: d.name):
        L.append(f"## {d.name}")
        L.append("")
        L.append(f"- **path**: `{d.path}`" + ("" if d.exists else "  (MISSING)"))
        size = f"{d.bytes:,} bytes" if isinstance(d.bytes, int) else "n/a"
        rec = f"{d.records:,}" if isinstance(d.records, int) else str(d.records)
        L.append(f"- **volume**: {rec} {d.record_unit}; {size}")
        if d.schema_fields:
            L.append(f"- **schema fields (sampled)**: {', '.join(d.schema_fields)}")
        L.append(f"- **produced by**: {d.produced_by}")
        L.append(f"- **selection**: {d.selection}")
        L.append(f"- **responder**: {d.responder}")
        if d.channel_candidacy:
            L.append("- **channel candidacy** (structural, not an admission):")
            for ch in LEDGER_CHANNELS:
                if ch in d.channel_candidacy:
                    L.append(f"  - _{ch}_: {d.channel_candidacy[ch]}")
        else:
            L.append("- **channel candidacy**: none identified")
        if d.units:
            L.append(f"- **measured units**: {', '.join(d.units)}")
        if d.summary:
            L.append(f"- **summary**: `{json.dumps(d.summary, sort_keys=True)}`")
        for n in d.notes:
            L.append(f"- _note_: {n}")
        L.append("- **open questions for the author's label rulings**:")
        for q in d.open_questions:
            L.append(f"  - {q}")
        L.append("")
    L.append("## Reconciliation against the 2026-07-08 inventory")
    L.append("")
    L.append("| source | quantity | expected | observed | match |")
    L.append("|---|---|---|---|---|")
    for r in recon:
        L.append(f"| {r['name']} | {r['quantity']} | {r['expected']} | "
                 f"{r['observed']} | {r['match']} |")
    L.append("")
    L.append("_A mismatch is a fact to explain, not a failure; live-log rows are "
             "minimums by design._")
    L.append("")
    return "\n".join(L)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def repo_root_from_here() -> str:
    # .../packages/governor_core/credence_governor_core/training/data_audit.py
    return os.path.abspath(os.path.join(os.path.dirname(__file__), *[".."] * 4))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-dir",
                    default=os.path.expanduser("~/.credence-governor/data-audit"),
                    help="where report.md and dossiers.json land")
    ap.add_argument("--heavy", action="store_true",
                    help="also line-count the ~56 GB raw capture")
    ap.add_argument("--root", default=repo_root_from_here(),
                    help="credence-governor checkout root")
    args = ap.parse_args(argv)

    dossiers = build_dossiers(args.root, heavy=args.heavy)
    recon = reconcile(dossiers)

    os.makedirs(args.out_dir, exist_ok=True)
    md_path = os.path.join(args.out_dir, "report.md")
    js_path = os.path.join(args.out_dir, "dossiers.json")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(dossiers_to_markdown(dossiers, recon))
    with open(js_path, "w", encoding="utf-8") as f:
        f.write(dossiers_to_json(dossiers, recon))

    print(f"data audit: {len(dossiers)} dossiers -> {md_path}")
    mismatches = [r for r in recon if r["match"] not in
                  ("yes", "yes (>= expected; live)", "not counted")]
    for r in mismatches:
        print(f"  reconciliation: {r['name']} {r['quantity']} expected "
              f"{r['expected']} observed {r['observed']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
