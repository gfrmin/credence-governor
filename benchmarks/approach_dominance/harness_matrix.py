# Role: eval
"""Per-harness live-axis matrix (§5.5 — neutral core + matrix + one in-the-loop smoke).

The dominance NUMBERS come from the harness-neutral oracle grid (routing) and corpus
(harm). What is harness-*specific* is only which axes are live and the integration tax.
This module keeps the "1–3 harnesses" claim honest about *what* each harness measures:

  * OpenClaw     — routing + governance (the adapter exposes model choice → routing is live).
  * Claude Code  — governance only (routing N/A until the harness exposes model choice).
  * neutral-core — the oracle-grid routing + the corpus harm (what the dominance map scores).

`drive_smoke` is the thin OpenClaw in-the-loop liveness check (not a measurement): it
confirms the eval's decisions actually flow through a real harness, so "1 driven + 2 mapped"
is honest. It is intentionally NOT part of the dominance numbers.
"""

from __future__ import annotations

HARNESS_MATRIX = {
    "openclaw": {"routing": "live", "governance": "live",
                 "note": "adapter exposes model choice → routing decisions flow through the harness"},
    "claude-code": {"routing": "n/a", "governance": "live",
                    "note": "no model-choice surface yet → routing not measurable; governance is live"},
    "neutral-core": {"routing": "oracle-grid", "governance": "corpus",
                     "note": "the harness-neutral substrate the dominance map is scored on (measured)"},
}


def live_axes(harness: str) -> dict:
    return HARNESS_MATRIX.get(harness, {})


def matrix_markdown() -> str:
    rows = ["| harness | routing | governance | what it measures |",
            "|---|---|---|---|"]
    for h, ax in HARNESS_MATRIX.items():
        rows.append(f"| {h} | {ax['routing']} | {ax['governance']} | {ax['note']} |")
    return "\n".join(rows)


if __name__ == "__main__":
    print(matrix_markdown())
