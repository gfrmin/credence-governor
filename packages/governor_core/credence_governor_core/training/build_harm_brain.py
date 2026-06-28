"""build_harm_brain.py — the reproducible build of data/brain/harm_brain.counts.json.

The shipped harm prior was built by an ad-hoc, uncommitted script on 2026-06-08
using a SEPARATE extractor copy (credence_pi_eval/analysis). This documents and
re-runs that procedure with ONE difference that is the whole point: it uses the
daemon's own ``extract_safety`` (train == runtime), killing the fork.

Procedure (pure data aggregation — no engine needed):

    corpus trajectory
      └─ for each proposed call:  extract_safety(event, session_so_far)  → 6-tuple context
      └─ reason-localized attribution: which call the human `reason` names as harmful
    accumulate per context:  n1 += harm-localized call (unsafe traj) ; n0 += everything else
    fold the curated benign-coding negatives as n0 (the FP corpus is training data)
    write {header + contexts:[{ctx,n0,n1}]}  — the warm prior the daemon replays via structure_bma

The attribution (``localize_harm``) is a SEPARATE concern from feature extraction
(Invariant 3): it decides WHICH call is harmful from the human reason text; the
extractor decides the call's CONTEXT. They share only ``safety.is_sink`` (the same
SINK/READ vocabulary), kept single-sourced.

    build:   python -m credence_governor_core.training.build_harm_brain <corpus.json> --out <out.json>
    verify:  python -m credence_governor_core.training.build_harm_brain <corpus.json> --verify <shipped.json>

`verify` reports the realignment delta between the shared-extractor counts and the
forked-trained shipped artifact — the gap M4 ships when it retrains.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import defaultdict

from ..config import HARM
from ..safety import extract_harm, is_sink
from .capture_corpus import load_capture
from .corpus import _atbench_events, iter_atbench_calls, load_atbench
from .fp_eval import benign_coding_calls
from .red_team import red_team_calls

# The shipped 6-tuple (M4 promoted taint-source + target-externality from candidate-
# measurement into config.HARM). Single source of truth: the order tracks config.HARM
# and the extractor is train==runtime, so build() reproduces the deployed posterior.
_CTX_KEYS = HARM["feature_names"]

# Attribution-only token rules (reason-text localisation). Deliberately NOT the
# extractor's token set — this is "which call does the human reason point at",
# a different question from "what is the call's taint context". Ported verbatim
# from credence_pi_eval/analysis/reason_attribution.py.
_ATTR_TOKEN_RES = [
    re.compile(r"[\w.+-]+@[\w.-]+\.\w+"),       # email
    re.compile(r"https?://[\w./?=&%+#~-]+"),    # url
    re.compile(r"(?:/[\w.+-]+){2,}/?"),         # deep path
]


def _arg_tokens(args: object) -> set[str]:
    try:
        txt = json.dumps(args).lower()
    except (TypeError, ValueError):
        txt = str(args).lower()
    toks: set[str] = set()
    for rx in _ATTR_TOKEN_RES:
        for mo in rx.finditer(txt):
            t = mo.group(0).rstrip("/.,);'\"")
            if len(t) >= 4:
                toks.add(t)
    return toks


def _record_toolcalls(record: dict) -> list[tuple[int, str, object]]:
    """Ordered (idx, name, args) over assistant toolCall blocks — the SAME idx
    convention as iter_atbench_calls (so attribution aligns with the feature stream)."""
    out: list[tuple[int, str, object]] = []
    idx = 0
    for e in _atbench_events(record):
        m = e.get("message", {})
        if m.get("role") != "assistant":
            continue
        c = m.get("content")
        if isinstance(c, list):
            for b in c:
                if isinstance(b, dict) and b.get("type") == "toolCall":
                    out.append((idx, b.get("name") or "", b.get("arguments") or {}))
                    idx += 1
    return out


def localize_harm(record: dict) -> set[int]:
    """Call indices the human `reason` localises as harmful, for an unsafe trajectory.
    Match a sink call whose name-token or distinctive arg-token is quoted in the reason;
    fallback to the last sink (the harmful action is typically the climax). Port of
    reason_attribution.reason_localized."""
    reason = (record.get("reason") or "").lower()
    calls = _record_toolcalls(record)
    hit: set[int] = set()
    for idx, name, args in calls:
        nm = (name or "").lower()
        name_toks = [t for t in re.split(r"[\s_\-]+", nm) if len(t) >= 3]
        name_match = bool(name_toks) and any(t in reason for t in name_toks)
        arg_match = any(tok in reason for tok in _arg_tokens(args))
        if (name_match or arg_match) and is_sink(name):
            hit.add(idx)
    if not hit:
        sinks = [idx for idx, name, _ in calls if is_sink(name)]
        if sinks:
            hit.add(sinks[-1])
    return hit


def accumulate(records: list[dict], ctx_keys: list[str] | None = None,
               ) -> tuple[dict[tuple[str, ...], list[int]], dict[str, int]]:
    """Per-context [n0, n1] over every call, using the shared extractor for the
    context and reason-localisation for the n1 (harm) label. ``ctx_keys`` selects the
    feature tuple (defaults to the shipped set, config.HARM; override only to measure a
    sub-/super-set against the same corpus)."""
    keys = ctx_keys or _CTX_KEYS
    counts: dict[tuple[str, ...], list[int]] = defaultdict(lambda: [0, 0])
    n_calls = n_harm = 0
    for i, record in enumerate(records):
        sid = record.get("trajectory", {}).get("session_id") or f"atbench-{i}"
        unsafe = not bool(record.get("labels", {}).get("is_safe", True))
        harm_idxs = localize_harm(record) if unsafe else set()
        for call in iter_atbench_calls(record, sid):
            feats = extract_harm(call.event, call.session)
            ctx = tuple(feats[k] for k in keys)
            n_calls += 1
            if call.idx in harm_idxs:
                counts[ctx][1] += 1
                n_harm += 1
            else:
                counts[ctx][0] += 1
    return counts, {"n_calls": n_calls, "n_harm_labelled": n_harm, "n_trajectories": len(records)}


def fold_benign_negatives(counts: dict[tuple[str, ...], list[int]],
                          calls, ctx_keys: list[str] | None = None) -> int:
    """Fold is_safe coding calls into existing counts as n0 — the FP/benign-coding
    corpus is TRAINING data, not just eval (everything is a feature; the posterior
    learns read-own → benign from these negatives, which ATBench cannot teach because
    it has no in-workspace reads). ``calls`` is an iterable of (event, session)."""
    keys = ctx_keys or _CTX_KEYS
    n = 0
    for event, session in calls:
        feats = extract_harm(event, session)
        counts[tuple(feats[k] for k in keys)][0] += 1
        n += 1
    return n


def fold_attack_positives(counts: dict[tuple[str, ...], list[int]],
                          calls, ctx_keys: list[str] | None = None) -> int:
    """Fold declared coding attacks as n1 POSITIVES — the attack-side twin of
    fold_benign_negatives. Each call IS the harmful action (call-level positive, the
    analogue of the red-team's all-positive cases), re-extracted by `extract_harm`
    (train==runtime). This is priors-as-data done honestly: known-threat *structure*
    written down as a declared corpus, not a posterior bent posthoc — the cell prior
    stays symmetric, risk-aversion stays in the utility H/λ. ``calls`` is an iterable
    of (event, session)."""
    keys = ctx_keys or _CTX_KEYS
    n = 0
    for event, session in calls:
        feats = extract_harm(event, session)
        counts[tuple(feats[k] for k in keys)][1] += 1
        n += 1
    return n


def _corpus_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build(corpus_path: str, corpus_label: str, *, fold_benign: bool = True) -> dict:
    """The full counts artifact (header + sorted contexts). Deterministic: contexts
    are sorted by tuple and no wall-clock stamp is embedded, so the same corpus +
    extractor reproduce byte-for-byte; provenance is the corpus SHA-256.

    ``fold_benign`` adds the curated benign-coding negatives as n0 (the FP corpus IS
    training data — it teaches read-own → benign, which the attack corpus cannot, having
    no in-workspace reads). Generic cells (local-write/none, external-send/internal) still
    need real-dogfood VOLUME to separate; the curated negatives only move the
    provenance-distinctive (read-own) cells. See M4 notes in the arc plan."""
    records = load_atbench(corpus_path)
    counts, stats = accumulate(records)
    n_benign = fold_benign_negatives(counts, benign_coding_calls()) if fold_benign else 0
    contexts = [
        {"ctx": list(ctx), "n0": n0, "n1": n1}
        for ctx, (n0, n1) in sorted(counts.items())
    ]
    return {
        "attribution": "reason-localized (the harmful call the human reason names)",
        "extractor": "credence_governor_core.safety.extract_safety (shared, causal, train==runtime)",
        "feature_names": list(_CTX_KEYS),
        "corpus": corpus_label,
        "corpus_sha256": _corpus_sha256(corpus_path),
        "n_calls": stats["n_calls"] + n_benign,
        "n_attack_calls": stats["n_calls"],
        "n_benign_negatives": n_benign,
        "n_harm_labelled": stats["n_harm_labelled"],
        "n_trajectories": stats["n_trajectories"],
        "n_contexts": len(contexts),
        "note": "Daemon reconstructs the posterior by replaying these counts via structure_bma.",
        "contexts": contexts,
    }


def build_coding(capture_path: str | None = None, *, include_truncated: bool = False) -> dict:
    """The coding-native harm brain (M4; docs/coding-threat-matched-harm-model.md §5).

    n1 = the declared coding red-team corpus (`red_team_calls`); n0 = the curated
    benign-coding negatives + (when a capture path is given) real captured dogfood
    traffic (`load_capture`). **ATBench is RETIRED for this body**: its content-semantic
    assistant attacks would re-pollute coding-benign cells (§4), and capture supplies the
    benign coding distribution directly (§5). The two halves use the SAME `extract_harm`
    the daemon runs (train==runtime).

    Deterministic: contexts sorted, no wall-clock embedded — same corpus + capture
    reproduce byte-for-byte; provenance is the capture path + the per-side counts."""
    counts: dict[tuple[str, ...], list[int]] = defaultdict(lambda: [0, 0])
    n1 = fold_attack_positives(counts, red_team_calls())
    n0_curated = fold_benign_negatives(counts, benign_coding_calls())
    n0_capture = (
        fold_benign_negatives(counts, load_capture(capture_path, include_truncated=include_truncated))
        if capture_path else 0
    )
    contexts = [
        {"ctx": list(ctx), "n0": n0, "n1": n1c}
        for ctx, (n0, n1c) in sorted(counts.items())
    ]
    return {
        "attribution": "call-level (the declared red-team proposed call IS the n1 positive; benign traffic is n0)",
        "extractor": "credence_governor_core.safety.extract_harm (shared 7-tuple, causal, train==runtime)",
        "feature_names": list(_CTX_KEYS),
        "corpus": "coding-native: declared red-team (n1) + curated-benign + captured dogfood (n0); ATBench retired",
        "capture_path": capture_path or "(none)",
        "n_calls": n1 + n0_curated + n0_capture,
        "n_attack_positives": n1,
        "n_benign_curated": n0_curated,
        "n_benign_captured": n0_capture,
        "n_contexts": len(contexts),
        "note": "Daemon reconstructs the posterior by replaying these counts via structure_bma.",
        "contexts": contexts,
    }


def _load_context_map(path: str) -> dict[tuple[str, ...], list[int]]:
    with open(path) as f:
        doc = json.load(f)
    return {tuple(c["ctx"]): [c.get("n0", 0), c.get("n1", 0)] for c in doc.get("contexts", [])}


def verify(corpus_path: str, shipped_path: str) -> dict[str, float]:
    """Report the realignment delta: shared-extractor counts vs the shipped
    (forked-trained) artifact. Same totals + small per-context drift is expected
    (the ~2% per-call feature divergence from validate_extraction); large drift is
    a regression in the build."""
    built = build(corpus_path, "verify")
    mine = {tuple(c["ctx"]): [c["n0"], c["n1"]] for c in built["contexts"]}
    shipped = _load_context_map(shipped_path)

    all_ctx = sorted(set(mine) | set(shipped))
    moved = 0
    print(f"{'context':<58}{'shipped n0/n1':>16}{'built n0/n1':>16}")
    for ctx in all_ctx:
        s = shipped.get(ctx)
        b = mine.get(ctx)
        if s != b:
            moved += 1
            print(f"{'/'.join(ctx):<58}{(str(s) if s else '—'):>16}{(str(b) if b else '—'):>16}")
    s_calls = sum(n0 + n1 for n0, n1 in shipped.values())
    s_harm = sum(n1 for _, n1 in shipped.values())
    print(f"\n{'':<10}{'n_calls':>10}{'n_harm':>10}{'n_contexts':>12}")
    print(f"{'shipped':<10}{s_calls:>10}{s_harm:>10}{len(shipped):>12}")
    print(f"{'built':<10}{built['n_calls']:>10}{built['n_harm_labelled']:>10}{built['n_contexts']:>12}")
    print(f"\ncontexts differing: {moved}/{len(all_ctx)} "
          f"(harm-total delta {built['n_harm_labelled'] - s_harm:+d}, call-total delta {built['n_calls'] - s_calls:+d})")
    return {
        "contexts_differing": moved,
        "harm_delta": built["n_harm_labelled"] - s_harm,
        "call_delta": built["n_calls"] - s_calls,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build/verify harm_brain.counts.json.")
    ap.add_argument("corpus", nargs="?", help="path to an ATBench test.json (legacy build/verify)")
    ap.add_argument("--coding", action="store_true",
                    help="build the coding-native brain (red-team n1 + capture/benign n0; ATBench retired) — the shipped M4 path")
    ap.add_argument("--capture", help="raw_events.jsonl path for the benign n0 (with --coding)")
    ap.add_argument("--out", help="write the counts artifact here")
    ap.add_argument("--verify", help="compare the shared-extractor build to this shipped counts.json (legacy ATBench)")
    ap.add_argument("--label", default="AI45Research/ATBench-Claw (test.json, Apache-2.0)",
                    help="corpus label recorded in the header")
    args = ap.parse_args(argv)

    if args.coding:
        doc = build_coding(args.capture)
        text = json.dumps(doc, indent=4)
        if args.out:
            with open(args.out, "w") as f:
                f.write(text + "\n")
            print(f"wrote {args.out}: {doc['n_calls']} calls "
                  f"({doc['n_attack_positives']} attack n1, {doc['n_benign_curated']}+{doc['n_benign_captured']} benign n0), "
                  f"{doc['n_contexts']} contexts")
        else:
            print(text)
        return 0

    if not args.corpus:
        ap.error("a corpus path is required unless --coding is given")
    if args.verify:
        verify(args.corpus, args.verify)
        return 0
    doc = build(args.corpus, args.label)
    text = json.dumps(doc, indent=4)
    if args.out:
        with open(args.out, "w") as f:
            f.write(text + "\n")
        print(f"wrote {args.out}: {doc['n_calls']} calls, {doc['n_harm_labelled']} harm-labelled, "
              f"{doc['n_contexts']} contexts")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
