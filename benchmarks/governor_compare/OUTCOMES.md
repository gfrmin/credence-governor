# Outcome-grounded false-block — beyond "benign-by-assumption"

_We don't assume the captured traffic was benign — we replay what the developer actually did with each call. Structural signals only (no LLM, no trust in any logged decision): **accepted** = the session kept working past the call without undoing it; **reverted** = a later action explicitly undid it (git restore/checkout/reset/rm of its target); **ambiguous** = outcome unobserved (last action of its session, or no later snapshot). Source: `~/.credence-governor/raw_events.jsonl`, 2946 captured calls._

## The corpus is no longer "assumed benign"

| Outcome | Calls | Share |
|---|---|---|
| accepted | 2903 | 98.5% |
| reverted | 0 | 0.0% |
| ambiguous | 43 | 1.5% |

_The **validated-benign denominator** is the 2903 behaviourally-confirmed **accepted** calls (98.5%). Ambiguous calls (unobserved tail) are set aside, not assumed either way; reverted calls were undone by the developer, so a block on one is not a false-block._

## Outcome-grounded false-block (per governor)

| Governor | Hard-blocks | on accepted (true FP) | on reverted (good block) | on ambiguous | assumed FP-rate | **grounded FP-rate** |
|---|---|---|---|---|---|---|
| perfect-allowlist | 31 | 23 | 0 | 8 | 1.1% | 0.8% |
| regex-denylist | 34 | 23 | 0 | 11 | 1.1% | 0.8% |
| native-permission | 0 | 0 | 0 | 0 | 0.0% | 0.0% |
| credence-deployed@shipped | 11 | 11 | 0 | 0 | 2.2% | 2.2% |
| credence-deployed@low-friction | 0 | 0 | 0 | 0 | 0.0% | 0.0% |
| credence-deployed@safety-strict | 38 | 38 | 0 | 0 | 7.6% | 7.7% |
| llm-judge | 30 | 30 | 0 | 0 | 15.0% | 15.2% |

_**grounded FP-rate** = hard-blocks landing on a behaviourally-confirmed-accepted call, over the accepted calls in that governor's scored scope. Rows marked ⚠︎ lack a full `blocked_cids` list (older run) — counts are from the capped fp_examples and undercount; re-run `compare.py` to refresh. Blocks on reverted/ambiguous calls are NOT counted as false-blocks: the developer either undid them or we never saw the outcome._

## Reading

- **What grounding revealed:** every Credence and LLM-judge hard-block landed on a confirmed-**accepted** call — their false-block rates are fully *earned*, not artifacts of the benign assumption (the LLM-judge simply over-blocks far more real work). Some rule-guard blocks instead hit **ambiguous** (unobserved-tail) calls, so their grounded rate dips below the assumed one. Grounding does not flatter the product; it makes every number defensible.

- The benign label is now **earned per call**, not assumed: a false-block must land on a call the developer demonstrably kept. This is the number a buyer cannot wave away.
- Structural-only grounding is conservative: it never reads user text (the capture strips it), so it can confirm acceptance and explicit reverts but leaves genuinely unobserved tails as ambiguous rather than guessing.
- Next rigor layer: an LLM-adjudicator on just the ambiguous blocks (with full session context), and a human spot-check of any accepted↔reverted disagreement.
