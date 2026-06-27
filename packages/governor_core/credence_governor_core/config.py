"""config.py — the governance domain, baked from the data/bdsl/ declarations into
the JSON the engine verbs take. The .bdsl files remain the human-authored source
of truth; this is the verb-payload projection. Keep in sync with
data/bdsl/{features,routing,utility}.bdsl. The brain/*.counts.json artifacts are
shipped inline (read at boot) to structure_bma / routing_init.

Port of credence-openclaw daemon/src/config.ts (values verbatim).
"""

from __future__ import annotations

# Governance (waste) brain — P(approve | waste-features). 6 features (data/bdsl/features.bdsl).
GOVERNANCE = {
    "feature_names": [
        "tool-name",
        "working-directory-relative",
        "parent-tool-call-name",
        "recent-repetition-count",
        "recent-identical-call-count",
        "time-since-last-user-message",
    ],
    "feature_values": [
        ["read", "write", "edit", "bash", "exec", "process", "apply_patch", "grep", "find", "ls", "other"],
        ["project-root", "subdirectory", "outside-project", "no-path"],
        ["read", "write", "edit", "bash", "exec", "process", "apply_patch", "grep", "find", "ls", "other", "none"],
        ["rep-0", "rep-1", "rep-2", "rep-3plus"],
        ["ident-0", "ident-1", "ident-2", "ident-3plus"],
        ["lt-30s", "lt-2m", "lt-10m", "gt-10m"],
    ],
    "warm_counts_file": "warm_brain.counts.json",
}

# Harm (safety) brain — P(unsafe | safety-features). 6 features (data/bdsl/features.bdsl §safety).
# M4 promoted taint-source (M2 provenance) + target-externality (M3) from candidate-
# measurement into the shipped feature set; the brain is retrained on the 6-tuple
# (build_harm_brain) and the extractor is train==runtime, so the order here must match
# build_harm_brain._CTX_KEYS and the features.bdsl safety-features list exactly.
HARM = {
    "feature_names": ["action-class", "taint-flow", "taint-source", "target-externality",
                      "injected-imperative", "cred-exfil-chain"],
    "feature_values": [
        ["read-only", "local-write", "delete", "exec", "external-send", "credential-access", "cross-boundary", "other"],
        ["none", "tainted-sink", "tainted-external-target"],
        ["web", "browser", "email", "message", "command-network", "marker",
         "read-external", "command-external", "local-external",
         "read-unknown", "command-unknown", "local-unknown",
         "read-own", "command-own", "local-own", "none"],
        ["external", "internal", "none"],
        ["no", "yes"],
        ["no", "yes"],
    ],
    "warm_counts_file": "harm_brain.counts.json",
}

# Routing — P(correct | prompt-length); EU-max over the roster (data/bdsl/routing.bdsl).
ROUTING = {
    "feature_names": ["prompt-length"],
    "feature_values": [["short", "medium", "long"]],
    "roster": [
        ["haiku", "anthropic", "claude-haiku-4-5", 0.0035],
        ["sonnet", "anthropic", "claude-sonnet-4-6", 0.0105],
        ["opus", "anthropic", "claude-opus-4-8", 0.0175],
    ],
    "warm_counts_file": "routing_brain.counts.json",
    "emission_prior": [2.0, 1.0, 1.0, 2.0],
}

# Declared utility/prior constants (data/bdsl/utility.bdsl; the default profile).
UTILITY = {
    "alpha0": 2.0,
    "beta0": 2.0,
    "p_edge": 0.5,        # cell prior + edge-inclusion prior
    "cost": 0.5,          # fallback-call-cost (dollars), when the body reports no priced turn
    "aversion": 1.0,      # false-block-aversion lambda
    "interrupt_cost": 0.02,  # interruption cost q (dollars)
    "harm_cost": 1.0,     # harm cost H (dollars) — multi-outcome governance ON
    "reward": 0.02,       # correct-answer-value (dollars) — the routing reward
}
