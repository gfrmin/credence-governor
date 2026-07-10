# Role: eval
"""outcomes.py — re-export of the outcome-grounding engine, now living in the library.

The structural session-replay classifier moved to
`credence_governor_core.training.outcomes` (post-hoc grounding is a first-class training
input, not a benchmark-only helper). This shim keeps the benchmark's local `import outcomes`
working unchanged — ground_outcomes.py and tests/test_outcomes.py consume it as before.
"""

from __future__ import annotations

from credence_governor_core.training.outcomes import *  # noqa: F401,F403
from credence_governor_core.training.outcomes import (  # noqa: F401  explicit names for linters
    Label,
    Outcome,
    SessionIndex,
    _canon,
    _is_error,
    _is_revert_of,
    _raw_records,
    _session_key,
    _target_path,
)
