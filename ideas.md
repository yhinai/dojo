> **Historical brainstorm:** The active project is shared-skill HERD. Start with [claude/HERD.md](claude/HERD.md) and its linked architecture. Earlier rankings, prize assumptions, and demo suggestions below are retained as history, not active instructions.

# Hackathon Ideas — CoreWeave Hacks (Agent Loops) + Open Model Hack

> Compiled Sept 12, 2026. Ranked by expected win probability given judges, past winners, sponsor-stack alignment, and build feasibility in the time box.

---

## 🏆 What actually wins this series (hard evidence)

This is the 4th edition of the W&B agent hackathon (WeaveHacks → CoreWeave Hacks). Past results:

| Edition | Winner | What it did |
|---|---|---|
| **WeaveHacks 3 Grand Prize** ($4k + robot dog) | **Aetheris V.O.** | "How can AI *teach you* instead of doing it for you?" Voice + screen-share overlay guiding users through tasks; every user interaction fed an RL improvement loop. Judges rewarded a human-in-the-loop *teaching* angle, not pure autonomy. Team lost WH1, won a sponsor prize in WH2, took grand prize in WH3 — iterated the same idea. |
| **WeaveHacks 3 notable** | **We've Been Through This** | Traces Claude Code sessions in Weave → distills each failure into a structured memory artifact (evidence + decision path + fix) → injects into future sessions via MCP. Literally "the agent learns from its own scars" — the exact phrase on the CoreWeave event page. |
| **WeaveHacks 3 notable** | **Mafia ACE** | Agents play Mafia tournaments; after each game each agent rewrites its strategy "cheatsheet" (ACE pattern). Full Weave tracing + LLM-as-judge evals on whether evolving cheatsheets improve win rate. |
| **WeaveHacks 2 winner pattern** | Resume RL optimizer | Writer agent vs. judge agent; score climbs visibly per iteration. |
| **Best Use of Weave (MCP edition)** | **RoboWeave** | Won largely on *demonstrable tracing/observability* of a Gemini Live robot planner. |

**The meta-pattern judges reward:**
1. A **visible, measurable improvement curve** across loop iterations (numbers on a dashboard, not vibes)
2. **Weave traces that make the loop legible** — judges are the Weave/ARIA/marimo teams
3. A **live demo where improvement happens in front of them**
4. A **twist** beyond "agent retries until it works"

---

## 🔬 Research frontier to steal from (2025–26)

| Paper | Core idea | Why it matters here |
|---|---|---|
| **ACE — Agentic Context Engineering** (Stanford/Microsoft, Oct 2025, `arxiv.org/abs/2510.04618`, code: `github.com/ace-agent/ace`) | Context as an evolving "playbook": Generator → Reflector → Curator; itemized strategy bullets with `helpful=X harmful=Y` counters; incremental delta updates prevent context collapse. +10.6% on agent benchmarks, matched top AppWorld agent with a smaller model. | The current SOTA blueprint for self-improving agents *without weight updates*. Mafia ACE used it only for a game — applying it to a real domain is wide open. |
| **Multi-Agent Evolve (MAE)** (`arxiv.org/pdf/2510.23595`) | Proposer / Solver / Judge triplet from one LLM, RL-trained; Proposer is *rewarded for generating problems the Solver fails at* → auto-escalating curriculum. +4.5% avg on Qwen2.5-3B. | Literally the "Agent Dojo" blueprint with published mechanics. |
| **SPIRAL** (`arxiv.org/html/2506.24119v3`) | Self-play on zero-sum language games (poker, negotiation) transfers to +10% on general reasoning benchmarks. | Evidence that adversarial self-play loops generalize — good "why it matters" slide. |
| **DEBATE, TRAIN, EVOLVE (DTE)** (EMNLP 2025, `aclanthology.org/2025.emnlp-main.1666.pdf`) | Multi-agent debate traces → distill into one model via GRPO; +8.9% avg, no ground truth needed. Documents failure modes: sycophancy (28% in small models), verbosity bias. | Gives you the failure-mode vocabulary judges will respect, and the "hall of mirrors" debate angle. |

---

# RANKED IDEAS

## 🥇 #1 — Agent Dojo: Agents That Train Each Other (CoreWeave Hacks)

**Build:** A dojo where agents teach each other a *real* skill — not a game. Three roles (from ACE/MAE):
- **Proposer** generates tasks of escalating difficulty (e.g., "make a reactive marimo plot with a slider")
- **Solver** attempts the task in a sandbox (marimo molab free GPUs — sponsor box ticked)
- **Judge** runs the code, grades it, and — critically — the Proposer is *rewarded when the Solver fails* (MAE trick), so the curriculum auto-ratchets to the frontier of the Solver's ability

The Solver maintains an **ACE-style playbook**: itemized lessons (`[str-00012] helpful=7 harmful=1 :: define each marimo variable in one cell and return it; execution follows the dependency graph`) that accumulate, get up/down-voted by execution feedback, and are pruned by the Curator role.

**The killer demo moment (30 seconds):** upload the evolved playbook to a *fresh, untrained* agent live on stage → it instantly outperforms its un-trained self. **Skill transfer across agents is the thing everyone talks about and nobody demos.**

**The honest-dojo twist (differentiator):** periodically inject a *wrong* lesson into the playbook. The Judge must catch and prune it via helpful/harmful counters. Now the dojo doesn't just learn — it **defends itself against its own bullshit**, addressing the #1 critique of self-improving loops (error amplification). Nobody else will demo an agent catching its own bad lesson.

### Why it wins
- Maps **verbatim** to the event page: "a dojo where agents train themselves," "a loop that learns from its own scars"
- Live, transferable demo with a visible improvement curve (the #1 judge pattern)
- Research-grounded (ACE + MAE) — judge Mo Tiwari (Google DeepMind) will recognize the lineage
- **Four prize categories from one codebase:**
  - *Best Loop Design* ($2k + robot dog + Fully Connected stage demo) — the flagship
  - *Best Use of Weave* ($1k) — trace every generation/reflection/curation call; LLM-as-judge scorers per round
  - *Best Use of ARIA* ($1k) — ARIA analyzes run history and recommends the next curriculum → **ARIA becomes the dojo's sensei**; almost nobody will attempt this
  - *Best Use of marimo* ($500) — live control-room dashboard: two curves (task difficulty rising, solver win-rate holding) = "the dojo finds the edge of competence and trains there"

### Pros
- On-theme to the letter; highest flagship-prize EV of any idea here
- Live demo is theatrical *and* rigorous (numbers + transfer test)
- Sponsor-stack integration is natural, not bolted on
- Playbook artifact is a tangible takeaway (judges can read the actual lessons)

### Cons / risks
- "Agents improve at a toy task" is the most common project shape at this series — **must** use a real skill domain (marimo API, Weave SDK) not Mafia/trivia (Mafia ACE already did Mafia)
- Three roles + playbook + dashboards = scope risk. **Freeze scope end of Day 1:** JSON playbook, 3 roles, 1 tool domain, Weave tracing, 1 marimo page. Day 2 = polish + the live transfer demo.
- Needs deterministic task verification (code runs → pass/fail) — pick a domain where the Judge has an objective oracle, not vibes

---

## 🥈 #2 — Loop Observatory / "Loop Doctor" (CoreWeave Hacks)

**Build:** Not a dashboard — a **doctor**. Detects live failure modes in a running agent and *intervenes*:
- **Spinning** — same action repeated
- **Thrashing** — oscillating between two approaches
- **Sycophancy drift** — agent abandons a correct answer after peer pressure (real measured failure: 28% in small models, per DTE)
- **Context rot** — early instructions stop influencing behavior as context grows

Each detector is a **Weave scorer over the trace stream**. When triggered, the doctor injects a targeted intervention: forced reflection, context compression, "re-read your original goal."

**Demo:** two identical agents side by side on the same task — one doctored, one not. The doctored one completes; the other spins until the audience laughs. Live contrast = great theater.

**Optional v2 ("Darwin"):** across runs, ARIA analyzes which loop configurations (retry count, reflection frequency, model per step) correlate with success and *reconfigures the agent's loop* for the next run — "closing the loop on the loop."

### Why it wins
- The most **Most Production-Ready**-shaped idea ($1k + F1 tickets category) — production agent reliability is CoreWeave/W&B's actual business
- Least crowded lane — most teams build agents; almost nobody builds the thing that *fixes* agents
- Uses ARIA as intended (analyze thousands of runs → recommend next iteration) → *Best Use of ARIA* shot
- Funny, legible demo (agents lying/spinning is instantly understood)

### Pros
- Smaller surface area than the Dojo — very achievable in the time box
- Strong production-readiness narrative → Fully Connected "Most Production-Ready" second-chance prize
- Every detector is a Weave scorer → *Best Use of Weave* eligibility by construction

### Cons / risks
- Pure observability demos are dry — **must intervene**, not just watch, or it reads as a Weave feature clone (they will notice)
- Detecting failure modes reliably in 24h is harder than it looks; pick 3 detectors max, fake the rest with scripted scenarios if needed
- Less "wow" ceiling than the Dojo's transfer moment — ceiling is "very useful" not "whoa"

---

## 🥉 #3 — Open Model Bake-Off Arena (Open Model Hack)

**Build:** A live eval harness. One real task (SQL generation, structured extraction from receipts), run across 4–5 open models (Gemma 3 sizes, Llama, Qwen, Mistral) served via Lambda/Respan, with automated scoring and a **cost/latency/quality Pareto front**.

**Punchline:** "the 4B model fine-tuned for 20 minutes beats the 27B zero-shot." Judges at an *open-model* event love hard evidence about open models.

### Why it wins
- Directly on the event's stated theme: "build with the latest open models, compare approaches, see how they perform on real problems"
- Numbers-first demo lands with DeepMind/Gradient/Lambda judges
- Uses Lambda credits (sponsor) + can route through Respan (sponsor)
- Fits the ~5.5-hour build window — it's an eval harness, not a product

### Pros
- Lowest build risk of any idea here
- Objective results = no judging subjectivity
- Easy to make a beautiful single-screen result (Pareto chart)

### Cons
- Prizes are mostly **credits** ($20k Nango credits 1st, $5k 2nd/3rd), not cash
- Lower wow-factor ceiling; "benchmark harness" can read as a tutorial unless the fine-tuning twist lands
- Fine-tuning on-site is time-risky — pre-stage the dataset and script

---

## #4 — Nango-Powered Offline-First Agent (Open Model Hack)

**Build:** A fine-tuned small open model (FunctionGemma 270M) handles intent parsing **locally**; **Nango** provides the actual integrations (Gmail, Calendar, Slack, GitHub). "Natural language → 3 real API actions across 3 services, planned by an open model, executed via Nango." Add schema validation + cloud escalation only when local checks fail.

### Why it wins
- The prize pool is literally **Nango credits** — building the best Nango showcase is maximum sponsor alignment
- Proven winning architecture: this exact local-first + verify + escalate pattern won the Cactus × Google DeepMind FunctionGemma hackathon (99% F1, 548ms)
- "Production use case" is the event's stated theme — this is production-shaped

### Pros
- Clear demo narrative: "what GPT does, free and offline, with numbers"
- Direct shot at the $20k Nango credit first prize
- Feasible in the time box with pre-staged fine-tuning data

### Cons
- Only relevant to the Open Model Hack, not CoreWeave
- Requires careful pre-work (synthetic dataset generation in hour one) or the fine-tune eats the whole day
- Integration demos can fail live (OAuth flows, network) — pre-auth everything

---

## #5 — Loop Lie Detector (CoreWeave Hacks, 1-day fallback)

**Build:** Cheap and nasty. An agent claims "done" — the detector verifies claims against the trace: did it actually call the tool it says it called? Does the output match the claim? Show a hall-of-shame reel of agents confidently lying.

### Why it could win
Funny, demoable in an hour, genuinely useful for production agents. *Best Social Media demo* ($1k) bait — the lie-reel video travels.

### Pros
- Fastest build on this list; great as a side submission
- High meme/share value

### Cons
- Thin flagship-prize case — it's a feature, not a system
- A vigilant judge may see it as one Weave scorer + a regex (because it is)

---

## Decision matrix

| Idea | Event | Flagship EV | Sponsor categories | Build risk | Demo wow | Rank |
|---|---|---|---|---|---|---|
| **Agent Dojo (real-skill + honest-dojo)** | CoreWeave | ★★★★★ | Weave, ARIA, marimo | Medium | ★★★★★ | **1** |
| **Loop Doctor (Observatory)** | CoreWeave | ★★★☆ | Weave, ARIA, Most Production-Ready | Medium-low | ★★★★ | **2** |
| **Open Model Bake-Off Arena** | Open Model | ★★★ | Lambda, Respan | Low | ★★★ | **3** |
| **Nango Offline-First Agent** | Open Model | ★★★★ | Nango (the whole pool) | Medium | ★★★★ | **4** |
| **Loop Lie Detector** | CoreWeave | ★★ | Social Media demo | Very low | ★★★ | **5** |

**Recommendation (CoreWeave):** Build the **Agent Dojo, variant 1+3** — a dojo that teaches agents a real tool, transfers the playbook to a fresh agent live on stage, and prunes its own bad lessons. Keep the **Loop Doctor** as the fallback if Day 1 scope blows up.

---

## Agent Dojo — build checklist (Day 1 freeze)

- [ ] Playbook store: JSON file, itemized bullets `[id] helpful=X harmful=Y :: lesson`
- [ ] Three roles: Proposer (task gen), Solver (sandbox exec), Judge (objective oracle + grader)
- [ ] Curator: deterministic delta-merge with dedup/prune (ACE-style, non-LLM where possible)
- [ ] Domain: ONE real tool (marimo API or Weave SDK), objective pass/fail (code runs → assertions)
- [ ] Difficulty ratchet: Proposer rewarded when Solver fails (MAE)
- [ ] Saboteur injection: N% wrong lessons; Judge prunes via counters
- [ ] Weave: `@weave.op()` on every role call; LLM-as-judge scorers per round; eval dashboard
- [ ] marimo: control room — task difficulty curve + solver win-rate curve + playbook browser
- [ ] Day 2: the **live transfer demo** (fresh agent + playbook vs. fresh agent without)

## References

- CoreWeave Hacks event: https://luma.com/coreweavehacks
- ACE: https://arxiv.org/abs/2510.04618 · https://github.com/ace-agent/ace
- MAE (Multi-Agent Evolve): https://arxiv.org/pdf/2510.23595
- SPIRAL: https://arxiv.org/html/2506.24119v3
- DTE (Debate, Train, Evolve): https://aclanthology.org/2025.emnlp-main.1666.pdf
- WeaveHacks 3 winners: https://www.linkedin.com/posts/wandb_weavehacks-3-grand-prize-winner-is-activity-7431819330570506240-Ht1c
- Mafia ACE (WH3): https://github.com/alexanderzliu/weavehacks3
- We've Been Through This (WH3): https://github.com/kirilligum/we-ve-been-through-this-weave-hackathon-260131
- Weave docs: https://docs.wandb.ai/weave/concepts/what-is-weave · ARIA: https://docs.wandb.ai/aria/overview
- FunctionGemma fine-tuning (for Open Model ideas): https://ai.google.dev/gemma/docs/functiongemma/finetuning-with-functiongemma
