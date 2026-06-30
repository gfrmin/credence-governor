# Role: eval
"""dataset.py — the coding task set for the cost/routing comparison.

A credible RouteLLM head-to-head needs coding tasks with a QUALITY SPREAD — problems the
cheap model sometimes fails and the strong model gets right — so a router's job (send the
hard ones to the strong model, the easy ones to the cheap one) is actually measurable.
HumanEval supplies exactly that, and grades OBJECTIVELY by executing the task's own unit
tests (no LLM-judge subjectivity on the quality axis).

Public dataset (MIT, openai/human-eval): 164 problems, each a function signature + docstring
(`prompt`), the target name (`entry_point`), and an executable `test`. We fetch-and-cache it
(gitignored) rather than vendoring, and record the source for provenance.
"""

from __future__ import annotations

import gzip
import json
import os
import urllib.request
from dataclasses import dataclass

HERE = os.path.dirname(__file__)
CACHE = os.path.join(HERE, ".humaneval.jsonl")
SOURCE = "https://github.com/openai/human-eval/raw/master/data/HumanEval.jsonl.gz"


@dataclass(frozen=True)
class CodingTask:
    task_id: str          # e.g. "HumanEval/0"
    prompt: str           # function signature + docstring the model completes
    entry_point: str      # the function name the test calls
    test: str             # executable check(candidate) unit tests


def _fetch(path: str) -> None:
    """Download + decompress HumanEval to a plain JSONL cache (once)."""
    req = urllib.request.Request(SOURCE, headers={"User-Agent": "credence-governor-bench"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = gzip.decompress(resp.read())
    with open(path, "wb") as f:
        f.write(raw)


def load_tasks(limit: int | None = None) -> list[CodingTask]:
    """Load (fetching+caching on first use) the HumanEval coding tasks."""
    if not os.path.exists(CACHE):
        _fetch(CACHE)
    tasks: list[CodingTask] = []
    with open(CACHE, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            tasks.append(CodingTask(r["task_id"], r["prompt"], r["entry_point"], r["test"]))
            if limit and len(tasks) >= limit:
                break
    return tasks
