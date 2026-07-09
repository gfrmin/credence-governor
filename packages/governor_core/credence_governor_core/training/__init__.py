from .build_harm_brain import (
    accumulate,
    build,
    build_coding,
    fold_attack_positives,
    fold_benign_negatives,
    localize_harm,
    verify,
)
from .cand_eval import (
    BUILTIN_CANDIDATES,
    CorpusSource,
    atbench_source,
    benign_coding_source,
    from_safety_feature,
    score_candidate,
    score_pooled,
)
from .capture_corpus import load_capture
from .corpus import LabeledCall, iter_atbench, load_atbench
# NB: ground_capture is intentionally NOT imported here — it is a `python -m` CLI, and
# eager-importing it would put it in sys.modules before `-m` runs it (a RuntimeWarning).
# Import it directly: `from credence_governor_core.training.ground_capture import ground`.
from .outcomes import Outcome, SessionIndex
from .fp_eval import (
    BENIGN_CODING_CASES,
    benign_coding_calls,
    evaluate_case,
    fp_firings,
    run_curated,
    snapshot_live_log,
)

__all__ = [
    "LabeledCall", "iter_atbench", "load_atbench", "load_capture",
    "Outcome", "SessionIndex",
    "BENIGN_CODING_CASES", "benign_coding_calls", "evaluate_case", "fp_firings",
    "run_curated", "snapshot_live_log",
    "accumulate", "build", "build_coding", "localize_harm", "verify",
    "fold_benign_negatives", "fold_attack_positives",
    "BUILTIN_CANDIDATES", "CorpusSource", "atbench_source", "benign_coding_source",
    "from_safety_feature", "score_candidate", "score_pooled",
]
