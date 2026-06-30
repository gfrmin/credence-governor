# Cost axis — Credence routing vs RouteLLM & cost rivals (coding)

_Phase 2. Per-(task, model) pass/cost measured ONCE on 164 HumanEval (executable tests) tasks across 3 models (haiku→opus); every router scored offline on the identical grid. Learned routers (routellm-style, credence) fit on 82 train tasks, decide on 82 test tasks. Realised cost = the chosen model's real grid cost._

## Cost vs quality (test split)

| Router | Pass-rate (quality) | Total cost | $/task |
|---|---|---|---|
| always-haiku | 95% | $0.1199 | $0.00146 |
| always-sonnet | 99% | $0.1892 | $0.00231 |
| always-opus | 100% | $0.2759 | $0.00336 |
| random | 96% | $0.1882 | $0.00230 |
| clairvoyant (bound) | 100% | $0.1208 | $0.00147 |
| frugal-cascade (bound) | 100% | $0.1312 | $0.00160 |
| routellm-style | 96% | $0.1844 | $0.00225 |
| credence@cost-saver (reward=0.02) | 95% | $0.1199 | $0.00146 |
| credence@indie-hacker (reward=0.02) | 95% | $0.1199 | $0.00146 |
| credence@balanced (reward=1.0) | 95% | $0.1199 | $0.00146 |
| credence@regulated-enterprise (reward=2.0) | 95% | $0.1199 | $0.00146 |
| credence@quality-first (reward=5.0) | 95% | $0.1199 | $0.00146 |
| credence@fintech-safety (reward=5.0) | 95% | $0.1199 | $0.00146 |

## What the coding data says

- **Cheap ≈ strong on coding.** always-haiku passes 95% vs always-opus 100% — a **5 pt** quality gap, at **57% lower cost**. The routing headroom (cheap fails, strong passes) is a handful of tasks.

- **The headroom exists but is unreachable without a difficulty signal.** The clairvoyant bound hits **100% at \$0.121** (≈ cheap-model cost) by sending only the few hard tasks to a strong model. But a simple prompt-length difficulty feature makes the models **per-bin indistinguishable** (each passes the same count per bin, just different tasks), so no *realisable* router reaches the bound — the win requires a difficulty signal none of these routers has.

- **Credence routes more cost-efficiently than RouteLLM-style here.** Credence lands at **\$0.120 / 95%** (= the cheap baseline), while routellm-style spends **\$0.184 / 96%** — **35% more cost for ~1pt of quality**. Because Credence's belief shows no per-bin quality difference, EU-max correctly declines to pay for the strong model at *every* buyer reward (cost-saver → quality-first all route cheap) — it doesn't chase quality the signal can't deliver.

- **The real anchor.** Credence's routing on **20 real multi-turn coding workloads** (`credence/data/benchmark-raw.json`, move-2): **~68% mean cost saving vs always-sonnet at 0 quality degradations** (opus-judged quality 7.1 vs 6.3). The router sent ~all turns to the cheap model and quality held — the same convergence this grid shows.

- **The differentiator is coverage, not cents.** RouteLLM/FrugalGPT/TokenShift are **cost-only point solutions** — zero harm and zero waste coverage. Credence reaches the same cost frontier *and* is the only governor that also blocks attacks (Phase 1) and averts waste. A buyer picks one governor spanning all axes, not three point tools.

## Cited rivals (published numbers — not run here)

- **RouteLLM** (cost only): open router; **~95% of GPT-4 quality at ~26% GPT-4 calls** (MT-Bench). Cost axis only — **zero harm/waste coverage**. On coding, where cheap≈strong, its routing converges to the same cheap-model policy measured here. [source](https://lmsys.org/blog/2024-07-01-routellm/)
- **FrugalGPT** (cost only): cheapest-first cascade with a learned verifier; our `frugal-cascade` row is its **clairvoyant upper bound** (stops at the first actually-correct rung). [source](https://arxiv.org/abs/2305.05176)
- **TokenShift / LLMLingua** (cost only): prompt COMPRESSION (orthogonal to routing); ~0.86× cost at claimed-preserved quality. Stacks with routing but covers neither harm nor waste. [source](https://github.com/microsoft/LLMLingua)

## Reading

- **Measured** rows ran offline on the identical coding grid; **cited** rows are published third-party numbers, tagged and linked, never blended.
- HumanEval frontier-model pass-rates are high (cheap ≈ strong), so this grid measures the **easy/standard-coding regime** where cost dominates. A harder regime (competition-level tasks with a real capability gradient) would stress routing QUALITY and is the natural next grid.
- The credence row is the engine's EU-max routing rule over the skin wire (per-(bin,model) Beta beliefs); the reward dial is the buyer profile.
