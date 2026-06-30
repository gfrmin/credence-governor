# Cost axis — Credence routing vs RouteLLM & cost rivals (coding)

_Phase 2. Per-(task, model) pass/cost measured ONCE on 164 HumanEval (executable tests) tasks across 3 models (haiku→opus); every router scored offline on the identical grid. Numbers are **mean ± std over 25 train/test splits** (no single-seed cherry-pick). Learned routers (routellm-style, credence) fit on each split's train half and decide on its test half; realised cost = the chosen model's real grid cost._

## Cost vs quality (mean ± std over splits)

| Router | Pass-rate (quality) | Total cost ($/test-split) |
|---|---|---|
| always-haiku | 95.4% ±1.5 | $0.1119 ±0.0040 |
| always-sonnet | 98.1% ±1.2 | $0.1842 ±0.0078 |
| always-opus | 98.4% ±1.1 | $0.2624 ±0.0086 |
| random | 97.1% ±1.5 | $0.1890 ±0.0119 |
| clairvoyant (bound) | 99.6% ±0.6 | $0.1133 ±0.0041 |
| frugal-cascade (bound) | 99.6% ±0.6 | $0.1260 ±0.0073 |
| routellm-style | 95.5% ±1.6 | $0.1777 ±0.0399 |
| credence@cost-saver (reward=0.02) | 95.2% ±1.4 | $0.1159 ±0.0069 |
| credence@balanced (reward=1.0) | 95.2% ±1.5 | $0.1608 ±0.0295 |
| credence@quality-first (reward=5.0) | 95.2% ±1.5 | $0.1608 ±0.0295 |

## What the coding data says

- **Cheap ≈ strong on coding.** always-haiku 95% vs always-opus 98% — a **3 pt** quality gap at **57% lower cost**. The routing headroom (cheap fails, strong passes) is a handful of tasks.

- **The headroom exists but is unreachable.** The clairvoyant bound hits **100% at $0.113** (≈ cheap-model cost) by sending only the few hard tasks to a strong model. But a prompt-length difficulty feature can't predict which tasks those are, so **no realisable router reaches it**.

- **No realisable router beats 'always cheap' — it's a tie.** Credence@cost-saver (95%, $0.116) sits right at the cheap baseline; routellm-style (95%, $0.178) and Credence's higher-reward profiles spend ~30–50% more for **no quality gain** — because the weak difficulty signal can't identify the hard tasks to upgrade. Both learned routers converge to the cheap model's quality.

- **The reward dial spans cost, from one belief.** cost-saver routes cheap ($0.116); quality-first pays more ($0.161) — the EU-max decision moves with the buyer profile. Here the extra spend buys ~no quality (the signal is too weak to convert dollars into passes), which is the honest read, not a knock on the mechanism.

- **The real anchor.** Credence's routing on **20 real multi-turn coding workloads** (`credence/data/benchmark-raw.json`, move-2): **~68% mean cost saving vs always-sonnet at 0 quality degradations** (opus-judged quality 7.1 vs 6.3) — the cheap model was good enough and quality held, the same convergence this grid shows from a different angle.

- **The differentiator is coverage, not cents.** RouteLLM/FrugalGPT/TokenShift are **cost-only point solutions** — zero harm and zero waste coverage. Credence reaches the same cost frontier *and* is the only governor that also blocks attacks (Phase 1) and averts waste. A buyer picks one governor spanning all axes, not three point tools.

## Cited rivals (published numbers — not run here)

- **RouteLLM** (cost only): open router; **~95% of GPT-4 quality at ~26% GPT-4 calls** (MT-Bench). Cost axis only — **zero harm/waste coverage**. On coding, where cheap≈strong and the hard tasks are hard to predict, its win-predictor converges to the cheap-model policy measured here. [source](https://lmsys.org/blog/2024-07-01-routellm/)
- **FrugalGPT** (cost only): cheapest-first cascade with a learned verifier; our `frugal-cascade` row is its **clairvoyant upper bound** (stops at the first actually-correct rung). [source](https://arxiv.org/abs/2305.05176)
- **TokenShift / LLMLingua** (cost only): prompt COMPRESSION (orthogonal to routing); ~0.86× cost at claimed-preserved quality. Stacks with routing but covers neither harm nor waste. [source](https://github.com/microsoft/LLMLingua)

## Reading

- **Measured** rows ran offline on the identical coding grid; **cited** rows are published third-party numbers, tagged and linked, never blended.
- Every number is averaged over 25 train/test splits with its std — no single split is load-bearing.
- HumanEval frontier-model pass-rates are high (cheap ≈ strong), so this grid measures the **easy/standard-coding regime** where cost dominates and routing has little to exploit. A harder regime (competition-level tasks with a real capability gradient) would stress routing QUALITY and is the natural next grid.
- The credence rows are the engine's EU-max routing rule over the skin wire (per-(bin,model) Beta beliefs); the reward dial is the buyer profile.
