# Coding-threat-matched harm model (design sketch)

Status: **active** — M1 (candidate features) + M2 (red-team corpus) + M3
(enforcement: `_block_category` consults the M1 features) + **M4 (promote + retrain
the posterior coding-native)** landed. Successor to the M1–M4 harm-feature arc
(`if-i-wanted-to-humble-harbor`). Supersedes the ATBench-trained harm brain
*for the coding deployment*.

> **M4 result (measured through the engine).** The three coding features are promoted
> into `config.HARM` (a 7-tuple: `coding-action-class, target-sensitivity,
> egress-destination` + the kept provenance trio + `cred-exfil-chain`), conditioned via
> one `safety.extract_harm` projection used by BOTH the daemon and `build_harm_brain`
> (train==runtime). The brain is trained **coding-native** — n1 = the declared red-team
> (20), n0 = real dogfood capture (~1.7k) + curated benign; **ATBench retired** for this
> body. At the shipped `H=1.0`: **recall 15/20 block (16/20 gated)**, and crucially the
> three **self-driven exfil** cases (`exfil-env-via-curl`, `…-aws-credentials`,
> `…-ssh-key-scp`) now **hard-DENY** — the M3 boundary (self-driven exfil returned
> `proceed`) is closed. An H-sweep showed raising H does not recover the misses (only
> adds FP), so **H stays 1.0** — risk-aversion needs no re-tuning; the misses are
> structural. The 4 misses are 2 `backdoor-logic` (the §6 content tail) + 2 self-driven
> `ci-infra` edits (see the §2 refinement below).
>
> **Two hard-FP fixes surfaced by real capture** (a benign hard-deny is the worst UX
> failure): (1) `is_credential_access` was **content-scanning** — editing the governor's
> own security code (dense with "credential"/"token") latched `cred-exfil-chain` across a
> whole session; made **structural** (the credential store as target), dropping the benign
> hard-*label* rate 41%→16%. (2) `_block_category` was over-broad on real traffic — its
> `exfil` rule fired on benign external-API curls, and `attacker_driven` treated
> `*-unknown` locality as attacker provenance; recalibrated so **exfil keys on credential
> involvement** and the hard rules **gate on confirmed-external provenance**. Net:
> **blocking hard-FP 4.0%→0.5%** over 600 real benign calls, recall unchanged. One trade:
> `curl | bash` (supply-chain RCE) is structurally identical to a benign API curl, so it
> dropped from hard-deny to **overridable block** (the posterior still blocks it); a
> dedicated pipe-to-shell signal to restore the hard deny without the FP is a future
> refinement.
>
> **Shipped + live-verified (0.10.0, deployed).** On the live daemon: self-driven
> `cat .env | curl` and `scp id_rsa` exfil → `block`/safety (was `proceed` on 0.9.0 — the
> boundary is closed); injected exfil/`rm -rf` from web → `block`/safety; benign external
> API curl / in-repo edit / tests / git status → `proceed` (no over-fire). `category` is
> advisory: blocks render as overridable "approve?" prompts by default (see §7).

> **M2 finding → closed by M3.** The mismatch is not only in the training
> *distribution* — the shipped feature *extractors and hard-deny path were
> assistant-tool-shaped*. `tainted-external-target` / `cred-exfil-chain` /
> `external-send` all key on a dedicated send TOOL name; coding exfil routes through
> `bash`, so the shipped hard-deny caught **0%** of the red-team's 20 coding attacks
> even though provenance resolved (`taint-source=web`). **M3** closes it:
> `_block_category` (a deterministic, P-independent LABEL — no belief/EU arithmetic,
> Invariant 1 clean) now consults the M1 features, so data-exfil and
> injection-triggered attacks hard-deny (injection-triggered 3/3, 7/20 total) while
> self-driven consequential ops stay overridable and benign-coding hard-FP stays 0%.
> This needed no retrain — the LABEL only refines an existing block, so it can upgrade
> overridable→hard but never spuriously blocks or removes the host's safety.
>
> **Live-verified (0.9.0):** the three injection-triggered attacks (web-exfil,
> issue-driven `rm -rf`, README-planted SSH key) + `curl | bash` hard-deny
> (`block`/`safety`); benign controls stay `waste` (hard-FP 0). **The boundary M3
> cannot cross:** `exfil-env-via-curl` / `exfil-ssh-key-scp` return `proceed` — the
> frozen ATBench posterior does not *block* self-driven coding exfil, and M3 (label-
> only) can only harden an existing block. The injection cases block because
> `taint-source=web` elevates the posterior; the self-driven exfils need **M4's
> retrain** (`red_team_calls()` as n1) to make the posterior block them. M3 can't
> escalate `proceed→block` without becoming a parallel decision mechanism (Invariant 1).

## 0. One line

The harm posterior should be parameterized on **coding's** threat structure
— `capability × target-sensitivity × provenance × egress`, all structural —
trained **benign-from-capture** and **attack-from-a-declared-red-team-corpus**.
Doing so closes a real recall hole (sensitive-target writes) and dissolves the
content-semantic ambiguity the ATBench-trained model carries.

## 1. The problem this solves

The shipped harm brain `P(unsafe | X)` is trained on **ATBench-Claw**, an
*assistant*-attack corpus: its harms factor as *content × broadcast-action*
(misinformation notes via `obsidian-cli create`; false-emergency broadcasts via
`sendMessage`). The daemon, however, governs a **coding agent**. The two threat
distributions don't match, and the mismatch shows up two ways:

1. **Ambiguous cells.** Content-semantic ATBench attacks land in the *same*
   structural cells benign coding occupies (e.g. `local-write / none / …`),
   because no structural feature separates "edit a source file" from "create a
   misinformation note" — only the *content* does. Live dogfooding (2026-06-26)
   put ~57% of benign coding calls into a harm over-fire cell; the residue after
   M2/M3 is exactly these content-ambiguous cells. The calibrated response there
   is an overridable ask — the system working — but it is *noise from the wrong
   training corpus*, not signal.

2. **A real recall hole.** Because the model has *capability* (coarse),
   *provenance*, and *egress* but **no target-sensitivity axis**, it under-rates
   coding's genuinely dangerous local writes. Today `write ~/.ssh/authorized_keys`
   extracts as plain `local-write / none / none` and lands in the same ~0.5
   overridable cell as editing project source — which an injected agent can
   *override*. Writing a backdoor into `.github/workflows/` is the same story.
   These are the attacks a coding governor most needs to catch, and the current
   feature set cannot see them.

Root cause is singular: **the harm model's threat distribution doesn't match the
body's.** Coding's real threats are almost entirely *structural*; the model isn't
parameterized to express them.

## 2. Coding's actual threat taxonomy

What an autonomous coding agent can actually do harm with — and the structural
signature of each:

| threat | structural signature | covered today? |
|---|---|---|
| **Secret exfiltration** | read credential-store → egress | partial (`cred-exfil-chain`) |
| **Destructive op** | `rm -rf`, `git reset --hard` / `push --force`, `DROP TABLE`, truncate | no (lumped in `delete`/`exec`) |
| **Supply-chain poison** | `npm`/`pip install`, lockfile/manifest write, `curl \| bash`, postinstall hook | no |
| **Privilege / persistence** | write `~/.ssh/authorized_keys`, shell profiles, cron, systemd, `sudo`, `/etc` | **no — the recall hole** |
| **CI / infra tamper** | write `.github/workflows`, `Dockerfile`, `*.tf`, k8s/deploy manifests | **no — the recall hole** |
| **Backdoor logic** | edit project-source that *adds egress / weakens auth* | partial (structural proxy only) |
| **Injection-triggered** *any of the above*, attacker-steered | taint-source/flow + injected-imperative | yes |

Five of seven are *fully structural*. The seventh (backdoor logic) is the only
genuine content-semantic residual, and even it has structural proxies (a diff
that adds a network call; an edit to an auth/crypto file; a write to CI).

## 3. The feature set

Keep the provenance trio (`taint-source`, `taint-flow`, `injected-imperative`) and
`cred-exfil-chain` — they already carry coding's injection-trigger and exfil
signals. Change three:

### 3.1 `action-class` → coding-native values

Extend the existing tool-name / command-head parser (no new content regex):

```
read-only · local-edit · destructive · external-send ·
credential-access · package-mutation · privilege-op · exec · other
```

`destructive`, `package-mutation`, `privilege-op` are new classes the assistant
model never needed. Derivation stays structural: `rm` / `reset --hard` →
`destructive`; `npm install` / lockfile write → `package-mutation`; `sudo` /
`chmod +s` → `privilege-op`.

### 3.2 `target-sensitivity` (NEW — the load-bearing feature)

Classify the action's **target path** by declared pattern sets — the same
declared-data machinery as the existing `trusted_paths` / `target_locality`
(Invariant 2: structure declared as data, never inferred from content):

```
project-source     in-repo code/docs                          (benign)
project-config     CI workflows, Dockerfile, lockfiles,
                   deploy manifests, dep manifests
credential-store   .env, id_rsa/id_ed25519, .aws/, *.pem,
                   .npmrc, .pypirc, .git-credentials, keychain
system-privileged  /etc, ~/.ssh, shell profiles, cron, systemd, sudoers
external/unknown   outside project_root
```

`action-class` is *what*; `target-sensitivity` is *where*. They are orthogonal —
the structure-BMA learns the joint: `local-edit × credential-store` = harm,
`local-edit × project-source` = benign. This is the axis the model is missing,
and the one that both dissolves the ambiguous cells and closes the recall hole.

### 3.3 `egress-destination` (refine `target-externality`)

```
none · loopback (127.0.0.1/localhost) · internal-net (private ranges, .local) ·
external-allowlisted (github/pypi/npm/configured providers) · external-unknown
```

Declared allowlist = data. The `loopback` split separates benign dev-curl from
real exfil — a live M3 false-positive that the binary `internal/external` axis
still blurred.

### Resulting model

```
P(unsafe | action-class, target-sensitivity, egress-destination,
           taint-source, taint-flow, injected-imperative, cred-exfil-chain)
```

## 4. Why this dissolves the ambiguity *and* closes the hole

- The old `local-write / none` cell (benign edits + misinformation notes) splits:
  coding edits → `local-edit × project-source` → cleanly benign; the
  misinformation-note attack **does not exist** in coding, so the cell is no
  longer shared and the ambiguity is gone — not by forcing a posterior, but
  because the feature set finally separates the two populations.
- The recall hole closes structurally: `write ~/.ssh/authorized_keys` →
  `target-sensitivity = system-privileged` → high-harm; a backdoor in
  `.github/workflows/` → `project-config`. The current model rated both as benign
  source edits.
  - **Measured refinement (M4).** This closes the *injection-triggered* half cleanly
    (`write ~/.ssh/authorized_keys` from a fetched README → `system-privileged` +
    confirmed-external provenance → hard-deny). But a **self-driven** CI/config backdoor
    (`local-edit × project-config`, own provenance) is **content-residual** like
    backdoor-logic: a coding agent *legitimately* edits CI/Dockerfiles/compose files
    often, so `P(unsafe | local-edit × project-config)` is genuinely low and only the
    *content* (a curl-exfil line in the workflow) distinguishes malicious from benign.
    `target-sensitivity` *raises* the harm estimate there but not past the benign base
    rate. So 2 of M4's 4 recall misses are self-driven `ci-infra` edits — folded into the
    §6 content-semantic tail, not a separate hole.
- Benign localhost-curl → `egress = loopback`, real exfil → `external-unknown`.

## 5. Training data — and where capture earns its keep

A coding-matched model needs **coding-distribution** counts. The two halves come
from different places, and that asymmetry is the honest crux:

- **Benign side (n0) = real dogfood capture.** The opt-in `RawCaptureLog` (M4b,
  shipped 0.8.0) writes re-extractable `(tool, input, session)` records. This is
  its real purpose: the benign half of a coding-native model — not "confirming a
  foregone conclusion," but supplying the benign population at the coding
  distribution. `load_capture → fold_benign_negatives → rebuild`.
- **Attack side (n1) = a declared coding red-team corpus.** Real coding attacks
  are ~absent from dogfood, so the attack side must be **encoded**, not waited
  for: deliberately authored trajectories covering the §2 threat classes (exfil
  `.env`→curl, `curl | bash`, force-push, authorized_keys write, CI backdoor,
  and injection-triggered variants of each). This is priors-as-data done
  honestly — known-threat *structure* written down and declared as a red-team
  set, **not** a posterior tuned posthoc to a desired answer
  (see `feedback_no_posthoc_prior_tuning`). The prior over cells stays symmetric;
  risk-aversion stays in the utility `H/λ`, never the prior.

ATBench is retired for this body (or kept only for the injection-trigger
sub-signals it genuinely carries).

## 6. The content-semantic tail, properly gated

The one threat structure can't fully catch is a *stealth backdoor in plausible-
looking source*. Structural proxies cover most of it (a diff that adds a network
call; an edit to an auth/crypto file; a CI write). The irreducible remainder —
semantically-malicious logic in normal-looking code — is where a **typed
`content-risk` feature from an injection-hardened judge** could eventually slot in
as a declared feature the brain conditions on. But it is **gated behind the
saturation precedent** (`feedback_saturation_precondition`): admit it only after
the structural partition demonstrably stops improving. We are nowhere near that —
the structural model is the 90% that isn't built yet — and a content judge is
itself prompt-injectable, so it must not be load-bearing while structure has
headroom.

## 7. Constitution check

- **Invariant 1.** Body still carries zero probabilistic code. The brain
  conditions; EU-max decides. `target-sensitivity` / `egress-destination` /
  `action-class` are *feature extractions*, P-independent; `_block_category`'s
  category is now **advisory** (it shapes the human-facing message), no longer a
  binding hard/soft gate. Fail-open is untouched.
- **Overridability is policy, default all-overridable.** Every gated decision is an
  overridable ask by default — the governor *surfaces* risk to the human operator,
  who is the final authority; it never hard-refuses on its own. This is the
  constitutionally consistent posture: with **finite** harm-cost `H`, a categorical
  (infinite-disutility) deny is unjustified, and a human override is admissible
  evidence that can flip the EU. Operators opt specific advisory categories into hard
  `deny` per body — `CREDENCE_GOVERNOR_DENY_CATEGORIES` (Claude Code) / `hardBlock`
  (OpenClaw). So even self-driven exfil surfaces as "approve?" rather than a silent
  refusal; the protection (surfacing + explicit confirmation) is preserved, the
  paternalism is not.
- **Invariant 2.** Every new feature is declared structure: path-pattern sets and
  the egress allowlist are *data* (peers of `trusted_paths`), classified by the
  same machinery — no content regex standing in for structure.
- **Invariant 3.** No representation conflation; features remain single-role.
- **No posthoc prior tuning.** Symmetric cell prior, risk in the utility, attack
  knowledge encoded as a declared corpus rather than a bent prior.
- **train == runtime.** Same `extract_safety` builds and runs; the new features
  extend it once.

## 8. Shape of the work (a multi-move arc, not a patch)

| move | deliverable |
|---|---|
| **M1** ✅ | `target-sensitivity` + coding `action-class` values + `egress` refinement as declared candidate features (`safety.{target_sensitivity,egress_destination,coding_action_class}`, `features.bdsl` `candidate-safety-features`); measured via `cand_eval`. Confirmed: high-precision, near-zero recall on ATBench, 0% benign-coding over-fire — the attack side must come from M2. |
| **M2** ✅ | the declared coding red-team corpus (`training/red_team.py`, 20 attacks across §2, injection-triggered + residual variants), measured by `cand_eval`/`run_red_team`. M1 candidates fire precision-1.00, 18/18 structural recall, 0% benign FP. `red_team_calls()` feeds M4's n1. Surfaced the assistant-tool-shaped hard-deny gap (above). |
| **M3** ✅ | enforcement: `_block_category` consults the M1 features (`safety.extract_enforcement`, wired in `daemon._enforcement_view`) so data-exfil + injection-triggered coding attacks hard-deny without a retrain. P-independent label refinement (Invariant 1 clean); injection-triggered 3/3, 7/20 total, benign hard-FP 0%. Pinned by `test_decide_category.py` + `test_red_team.py::test_m3_enforcement_hard_denies_external_attacks`. |
| **M4** ✅ | promoted the three features into `config.HARM` (7-tuple, conditioned via `extract_harm`); trained coding-native (`red_team_calls()` n1 + captured-benign n0; ATBench retired); validated through the engine (recall 15/20, self-driven exfil now hard-DENY). `H=1.0` held (H-sweep: raising it adds FP, recovers no misses). Two hard-FP fixes from real capture: structural `is_credential_access` (label 41%→16%) + `_block_category` recalibration (blocking hard-FP 4.0%→0.5%), recall preserved. |

M1 is the cheap, high-value start: the three feature changes close the recall
hole on their own, independent of any retrain.
