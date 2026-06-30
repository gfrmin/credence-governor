# Role: eval
"""oracle.py — extract once, score many: the coding cost/quality grid.

For every (task, model) we generate a solution ONCE, execute the task's own unit tests to
grade it objectively (pass/fail), and price the call from its token counts. The result —
per-(task, model) {passed, cost, tokens} — is the apples-to-apples invariant Phase 2 rests
on: every router (Credence, RouteLLM-style, cascades, fixed baselines, the clairvoyant
bound) is then scored OFFLINE on this identical grid, so cost/quality differences are the
router's, not noise from re-sampling the models.

The grid is written incrementally (one JSONL line per cell) and resumable: a re-run skips
cells already present, so an interrupted/expanded run never re-pays for a cell.

Model calls use Anthropic's OpenAI-compatible endpoint (key from the keyring):
    ANTHROPIC_API_KEY=$(secret-tool lookup service env key ANTHROPIC_API_KEY)
Grading executes model-generated code in an ISOLATED subprocess with a hard timeout; the
tasks are benign HumanEval problems, but the timeout + `-I` are the containment.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from dataclasses import asdict, dataclass

import dataset as D

HERE = os.path.dirname(__file__)
GRID = os.path.join(HERE, "coding_grid.jsonl")   # committed fixture (real measured data; costs API to regen)
ENDPOINT = "https://api.anthropic.com/v1/chat/completions"

# Roster: model -> (input $/1k, output $/1k) — mirrors the engine provider.py price table.
ROSTER: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5": (0.001, 0.005),    # cheap
    "claude-sonnet-4-6": (0.003, 0.015),   # mid
    "claude-opus-4-6": (0.005, 0.025),     # strong
}

_SYS = (
    "You are a Python coding assistant. Complete the given function. Return ONLY a single "
    "```python code block containing the COMPLETE function definition (with any imports it "
    "needs) — no explanation, no examples, no prose."
)


@dataclass
class Cell:
    task_id: str
    model: str
    passed: bool
    in_tokens: int
    out_tokens: int
    cost: float
    wall_s: float
    error: str = ""


def _generate(model: str, prompt: str, key: str) -> tuple[str, int, int, float]:
    """One model completion of a coding prompt → (text, in_tokens, out_tokens, wall_s)."""
    body = {"model": model, "max_tokens": 1024,
            "messages": [{"role": "system", "content": _SYS},
                         {"role": "user", "content": prompt}]}
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    t = time.monotonic()
    req = urllib.request.Request(ENDPOINT, data=json.dumps(body).encode(), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=120) as resp:
        j = json.loads(resp.read().decode())
    text = j["choices"][0]["message"]["content"] or ""
    u = j.get("usage", {})
    return text, u.get("prompt_tokens", 0), u.get("completion_tokens", 0), time.monotonic() - t


_FENCE = re.compile(r"```(?:python)?\s*\n(.*?)```", re.DOTALL)


def _extract_code(text: str, entry_point: str, prompt: str) -> str:
    """Pull the function code from the model reply; fall back to completing the prompt body."""
    m = _FENCE.search(text)
    code = m.group(1) if m else text
    # If the model returned only a body (no signature), graft it onto the task prompt.
    if f"def {entry_point}" not in code:
        return prompt + "\n" + code
    return code


def _grade(task: D.CodingTask, code: str, timeout: float = 12.0) -> tuple[bool, str]:
    """Execute the candidate against the task's own unit tests in an isolated subprocess."""
    program = f"{code}\n\n{task.test}\n\ncheck({task.entry_point})\n"
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "cand.py")
        with open(path, "w") as f:
            f.write(program)
        try:
            r = subprocess.run([sys.executable, "-I", path], cwd=td, capture_output=True,
                               text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return False, "timeout"
        if r.returncode == 0:
            return True, ""
        return False, (r.stderr.strip().splitlines() or [""])[-1][:160]


def _score_cell(task: D.CodingTask, model: str, key: str) -> Cell:
    in_p, out_p = ROSTER[model]
    try:
        text, nin, nout, wall = _generate(model, task.prompt, key)
    except Exception as e:  # an API error → a no-cost miss, recorded honestly
        return Cell(task.task_id, model, False, 0, 0, 0.0, 0.0, error=f"gen:{e}")
    code = _extract_code(text, task.entry_point, task.prompt)
    passed, err = _grade(task, code)
    cost = (nin * in_p + nout * out_p) / 1000.0
    return Cell(task.task_id, model, passed, nin, nout, round(cost, 6), round(wall, 2), error=err)


def _done(path: str) -> set[tuple[str, str]]:
    seen: set[tuple[str, str]] = set()
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    c = json.loads(line)
                    seen.add((c["task_id"], c["model"]))
    return seen


def build_grid(tasks: list[D.CodingTask], models: list[str], out_path: str = GRID,
               key: str | None = None) -> int:
    """Fill the (task × model) grid, resuming past any cells already present. Returns new cells."""
    key = key or os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        raise SystemExit("ANTHROPIC_API_KEY not set (secret-tool lookup service env key ANTHROPIC_API_KEY)")
    seen = _done(out_path)
    todo = [(t, m) for t in tasks for m in models if (t.task_id, m) not in seen]
    print(f"grid: {len(tasks)} tasks × {len(models)} models = {len(tasks)*len(models)} cells; "
          f"{len(seen)} cached, {len(todo)} to score")
    n = 0
    with open(out_path, "a", encoding="utf-8") as f:
        for t, m in todo:
            cell = _score_cell(t, m, key)
            f.write(json.dumps(asdict(cell)) + "\n")
            f.flush()
            n += 1
            if n % 10 == 0:
                print(f"  scored {n}/{len(todo)} (last: {t.task_id} {m} pass={cell.passed})", flush=True)
    return n


def load_grid(path: str = GRID) -> dict[tuple[str, str], Cell]:
    """Load the grid as {(task_id, model): Cell}."""
    out: dict[tuple[str, str], Cell] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                c = json.loads(line)
                out[(c["task_id"], c["model"])] = Cell(**c)
    return out


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="number of tasks (0 = all 164)")
    ap.add_argument("--models", default=",".join(ROSTER))
    args = ap.parse_args()
    tasks = D.load_tasks(limit=args.limit or None)
    models = [m for m in args.models.split(",") if m in ROSTER]
    added = build_grid(tasks, models, key=os.environ.get("ANTHROPIC_API_KEY"))
    grid = load_grid()
    # quick spread report — how many models pass each task (the discrimination we need)
    from collections import Counter
    per_task: dict[str, int] = {}
    for (tid, _m), c in grid.items():
        per_task[tid] = per_task.get(tid, 0) + (1 if c.passed else 0)
    spread = Counter(per_task.values())
    print(f"added {added} cells. pass-count spread (models passing per task): {dict(sorted(spread.items()))}")
    for m in models:
        cells = [c for (t, mm), c in grid.items() if mm == m]
        if cells:
            pr = sum(c.passed for c in cells) / len(cells)
            tc = sum(c.cost for c in cells)
            print(f"  {m:<22} pass-rate={pr:.1%}  total-cost=${tc:.3f}  n={len(cells)}")
