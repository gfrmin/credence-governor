# Harm-feature training platform (M1)

The offline pipeline that builds and validates the **frozen harm prior**
(`../data/brain/harm_brain.counts.json`, the `P(unsafe | X)` warm counts the
daemon replays via `structure_bma`). Pure data aggregation — **no engine needed**;
the engine enters only at runtime.

The load-bearing discipline: every stage runs the daemon's **own**
`credence_governor_core.safety.extract_safety` (train == runtime), replacing the
forked `credence_pi_eval` extractor that trained the shipped artifact.

## The four modules

| module | role |
|---|---|
| `corpus.py` | public agent-safety corpora → the neutral `(AgentToolEvent, Session)` stream, one `LabeledCall` per proposed call (causal: the session carries only prior messages). ATBench-Claw today; InjecAgent/AgentDojo/R-Judge/AgentHarm at M4. |
| `validate_extraction.py` | does the live extractor reproduce the canonical (forked) per-call features? Reports per-feature agreement. Result: action-class/cred-exfil 100%, taint-flow 98.2%, injected-imperative 97.6% (divergences are canon-fires-live-none). |
| `build_harm_brain.py` | the reproducible counts-build: corpus → `extract_safety` context + reason-localized harm attribution → `n0/n1` per `[action-class, taint-flow, injected-imperative, cred-exfil-chain]`. `--verify` reports the realignment delta vs the shipped artifact. |
| `fp_eval.py` | the **benign coding-agent false-positive** eval (the attack corpora are assistant-attack; the deployment is a coding agent). Curated re-extractable cases + `snapshot_live_log()` for the real-distribution baseline. |
| `cand_eval.py` | scores any candidate harm feature `(event, session) -> bool` — harm precision/recall/lift on attack corpora **and** fire-rate on benign coding, in one pass. Makes M2/M3 features measured, not asserted. |

## Corpus staging

Raw corpora live under `../../data_corpora/` (**gitignored** — large; only the
trained `*.counts.json` is committed). Corpus-dependent tests skip when absent.

ATBench-Claw (`AI45Research/ATBench`, Apache-2.0): stage `test.json` (500-traj
slice) at `data_corpora/atbench_claw/test.json`. `events.jsonl` (the canonical
per-call features, keyed `(session_id, idx)`) backs `validate_extraction.py`.

## Commands

```bash
cd packages/governor_core
P="PYTHONPATH=."   # or run under uv

# does the live extractor reproduce the canonical features?
$P python -m credence_governor_core.training.validate_extraction \
    data_corpora/atbench_claw/test.json data_corpora/atbench_claw/events.jsonl

# build the harm prior (deterministic; corpus-SHA provenance in the header)
$P python -m credence_governor_core.training.build_harm_brain \
    data_corpora/atbench_claw/test.json --out /tmp/harm_brain.json

# realignment delta vs the shipped (forked-trained) artifact
$P python -m credence_governor_core.training.build_harm_brain \
    data_corpora/atbench_claw/test.json --verify credence_governor_core/data/brain/harm_brain.counts.json

# false-positive rate on benign coding (+ the live-log baseline)
$P python -m credence_governor_core.training.fp_eval ~/.credence-governor/observations.jsonl

# score the built-in candidates (attack recall vs coding FP)
$P python -m credence_governor_core.training.cand_eval data_corpora/atbench_claw/test.json
```

## Current state (M1 baseline)

- **Build is faithful**: `n_calls` 2634 and `n_harm_labelled` 217 reproduce
  exactly; the shared extractor reassigns 22/30 contexts (30→25 collapse),
  entirely in `taint-flow`/`injected-imperative` — the forked extractor was
  non-causal + provenance-aware, the live one causal + provenance-blind.
- **The coding FP gap**: 57% of real benign coding calls trip a harm over-fire
  (8% would be hard-denied). `cand_eval` localises it to two features —
  `injected-imperative` (11% coding FP) and `action=external-send` (22%) — while
  `tainted-external-target`/`cred-exfil-chain` are clean (0% FP, lift >10).

M2 (provenance-aware seeding) closes the `injected-imperative`/taint FP; M3
(structure-based `action_class`) closes the `external-send` FP. M4 rebuilds the
prior with the M2+M3 extractor and ships. The shipped artifact stays **frozen**
until then.

## Coding-threat-matched candidates (next arc, M1)

`cand_eval` also scores the **coding-threat-matched** candidates
(`docs/coding-threat-matched-harm-model.md`): `target-sensitivity` (the missing
*where* axis — `credential-store` / `system-privileged` / `project-config` / …),
the `egress-destination` refinement (`loopback` / `external-allowlisted` / …),
and the coding-native `action-class` values (`destructive` / `package-mutation` /
`privilege-op`). They are CANDIDATES — declared in `features.bdsl`
(`candidate-safety-features`), extracted by `safety.{target_sensitivity,
egress_destination,coding_action_class}`, but NOT in the shipped `config.HARM`
tuple, so the frozen brain stays train==runtime. The eval confirms the thesis:
these structural features fire with high precision but **near-zero recall on
ATBench** (an assistant-attack corpus has few coding-structural threats) — so the
attack side must come from a declared coding red-team corpus (the next arc's M2),
not ATBench.
