# Role: eval
"""swebench.py — SWE-bench Verified gold trajectories as a PUBLIC success anchor.

Each SWE-bench Verified instance ships a gold `patch` that the SWE-bench harness has already
CONFIRMED resolves the task (its FAIL_TO_PASS tests turn green). We do NOT run an agent or a
docker eval — the resolution is given, verified, public. Instead we synthesize the canonical
solving trajectory the gold patch implies — for each source file the patch touches: a `read`,
then an `edit` writing the patched lines; then a final `bash` running the FAIL_TO_PASS tests —
as harness-neutral tool-call events. Each governor is then asked the success-axis question on a
clean public set: *would you have PERMITTED this verified solution path?* A hard block anywhere
on it is a governor that would have broken a real, correct fix.

This is a faithful cross-check of the real-session completion number, on contamination-free
OSS code (the captured corpus mixes in this safety system's own attack-fixture strings; SWE-bench
does not). Its honest limit: it scores the KNOWN-GOOD solution PATH, not an autonomous agent's
wandering trajectory or resolved-rate — that heavier run (real agent + docker) is the future
upgrade. Here, permitting the gold path is necessary for an agent to resolve via it.

Fetched once from the HF datasets-server, slimmed, and cached as a committed fixture
(swebench_verified_sample.jsonl) — reproducible without re-fetch, exactly like the cost grid.

    fetch the fixture (once):  python benchmarks/governor_compare/swebench.py --fetch --n 30
"""

from __future__ import annotations

import json
import os
import random
import urllib.request
from dataclasses import dataclass

from credence_governor_core.schema import AgentToolEvent, Message, Session

import streams as S

HERE = os.path.dirname(__file__)
FIXTURE = os.path.join(HERE, "swebench_verified_sample.jsonl")   # committed: public, slim, reproducible
DATASET = "princeton-nlp/SWE-bench_Verified"
_ROWS_URL = ("https://datasets-server.huggingface.co/rows?dataset=" + DATASET.replace("/", "%2F")
             + "&config=default&split=test&offset={off}&length={n}")


@dataclass
class Instance:
    instance_id: str
    repo: str
    patch: str
    fail_to_pass: list[str]


# ── fetch + cache the slim fixture ────────────────────────────────────────────
def _fetch_rows(n: int) -> list[dict]:
    rows: list[dict] = []
    off = 0
    while len(rows) < n:
        url = _ROWS_URL.format(off=off, n=min(100, n - len(rows)))
        with urllib.request.urlopen(url, timeout=60) as r:
            batch = json.load(r).get("rows", [])
        if not batch:
            break
        rows.extend(x["row"] for x in batch)
        off += len(batch)
    return rows


def fetch(n: int = 30, seed: int = 11, out_path: str = FIXTURE) -> int:
    """Pull a seeded sample of n Verified instances, slim to the fields the anchor needs,
    write the committed fixture. Sampling a contiguous head would bias toward one repo
    (the set is grouped), so we draw a seeded random subset over a larger pull."""
    pool = _fetch_rows(min(500, max(n * 6, 120)))
    pick = sorted(random.Random(seed).sample(range(len(pool)), min(n, len(pool))))
    with open(out_path, "w", encoding="utf-8") as f:
        for i in pick:
            r = pool[i]
            ftp = r.get("FAIL_TO_PASS")
            if isinstance(ftp, str):
                ftp = json.loads(ftp)
            slim = {"instance_id": r["instance_id"], "repo": r["repo"],
                    "patch": r["patch"], "fail_to_pass": ftp or []}
            f.write(json.dumps(slim) + "\n")
    return len(pick)


def load(path: str = FIXTURE) -> list[Instance]:
    out: list[Instance] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                d = json.loads(line)
                out.append(Instance(d["instance_id"], d["repo"], d["patch"], d["fail_to_pass"]))
    return out


# ── unified-diff → the files a fix touches + the lines it writes ──────────────
def parse_patch(patch: str) -> list[tuple[str, str]]:
    """[(path, added_text)] for each file in a gold patch. The gold `patch` is the SOLUTION
    (source files only; test files live in the separate `test_patch`), so these are exactly
    the legit edits a developer makes to fix the issue. We collect added (`+`) lines as the
    written content — faithful for governance feature extraction (it's the real code being
    written), and we need no base checkout to apply hunks."""
    files: list[tuple[str, str]] = []
    cur: str | None = None
    added: list[str] = []
    for line in patch.splitlines():
        if line.startswith("+++ b/"):
            if cur is not None:
                files.append((cur, "\n".join(added)))
            cur, added = line[6:], []
        elif line.startswith("+") and not line.startswith("+++"):
            added.append(line[1:])
    if cur is not None:
        files.append((cur, "\n".join(added)))
    return files


# ── synthesize the gold solving trajectory as harness-neutral tool-calls ──────
def synth_trajectory(inst: Instance) -> list[S.LabeledCall]:
    """The canonical solve: read each touched file → edit it to the gold lines → run the
    failing tests. Each call carries the accumulated session (so provenance / loop / taint
    features see real history). All calls are legit (is_harm=False), source='public'."""
    root = f"/repo/{inst.repo}"
    trusted = [root]
    msgs: list[Message] = []
    calls: list[S.LabeledCall] = []
    files = parse_patch(inst.patch) or [(f"{inst.repo}/CHANGED", "")]

    def emit(tool: str, inp: dict) -> None:
        sess = Session(cwd=root, project_root=root, trusted_paths=list(trusted), messages=list(msgs))
        calls.append(S.LabeledCall(AgentToolEvent(tool_name=tool, input=inp), sess,
                                   cid=f"{inst.instance_id}#{len(calls)}", is_harm=False,
                                   stream="swebench-gold", source="public"))
        msgs.append(Message(role="tool_call", tool_name=tool, input=inp))
        msgs.append(Message(role="tool_result", tool_name=tool, result="ok"))

    for path, added in files:
        emit("read", {"file_path": f"{root}/{path}"})
        emit("edit", {"file_path": f"{root}/{path}", "new_string": added[:2000]})
    # the realistic, friction-discriminating step: run the now-passing failing tests.
    tests = " ".join(inst.fail_to_pass[:3]) or "tests"
    emit("bash", {"command": f"python -m pytest {tests}"})
    return calls


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true", help="(re)build the committed fixture from HF")
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--seed", type=int, default=11)
    args = ap.parse_args()
    if args.fetch:
        k = fetch(args.n, args.seed)
        print(f"wrote {k} SWE-bench Verified instances → {FIXTURE}")
    insts = load()
    ncalls = sum(len(synth_trajectory(x)) for x in insts)
    print(f"loaded {len(insts)} instances; synthesized {ncalls} gold-trajectory tool-calls "
          f"({ncalls / max(1, len(insts)):.1f} calls/task)")
