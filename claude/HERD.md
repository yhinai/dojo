# HERD — One agent struggles. Every agent learns.

> **Active proposal, September 13, 2026.** This replaces verifier-hardening HERD as the product direction. The earlier design is preserved in [archive/verifier-herd-v1](archive/verifier-herd-v1/README.md).
>
> **Scope retained:** one initial tool ecosystem, marimo; five learner agents; three learning rounds; repair and lesson distillation; a shared versioned skill pool; cross-agent admission trials; PACE-style statistical gating; behavioral verification; regression and poisoning controls; Weave; an interactive marimo control room; ARIA analysis; full transfer evaluation.
>
> **Status:** architecture and experiment specification, not an implemented or measured system. The accompanying reference protocol checker validates selected design properties only.

## 1. Recommendation and honest assessment

**Yes: this is the stronger hackathon direction.** It makes the improvement target the agent's ability to complete a useful tool task. It connects the sponsor stack directly to the product: agents learn marimo, marimo displays their work, and Weave records the learning evidence.

Keep the five agents and three rounds. Astra and Fable can divide implementation work across clear interfaces; their availability is a reason to parallelize engineering, not evidence that model experiments or statistical validation will finish instantly. The build plan retains the full requested system and makes its dependencies explicit.

The proposed wording needs four corrections:

1. **The sample marimo lesson is false.** A cell can reference a global defined in a visually later cell because execution follows the dependency graph. A better initial lesson concerns duplicate global definitions, cell-local temporary names, or reactive computation from UI values. [Official execution model](https://docs.marimo.io/guides/reactivity/)
2. **The proposed same-session retry does not isolate shared learning.** Start two independent fresh workers on the same held-out task, one with the pool and one without it. Neither sees the other's trace or the source agent's repaired notebook.
3. **PACE supplies conditional statistical evidence, not proof that a lesson always helps.** Five learners and three rounds are not fifteen independent transfer observations. Admission requires a separate stream of paired worker evaluations.
4. **Tool-call success is insufficient.** A notebook can launch while computing the wrong answer or ignoring the slider. The trusted evaluator must check the requested behavior under changed inputs.

The earlier verifier project also had meaningful sponsor use and a real reliability problem. The new direction wins on the clarity of its learning outcome and presentation, not because the old integrations were inherently forced or verifier quality is unimportant.

## 2. Problem and customer

Agents operating in separate sessions often repeat tool-specific mistakes when no mechanism carries verified experience between them. A successful local repair can disappear with the conversation, or become an untested memory entry that causes new mistakes elsewhere.

HERD converts successful repairs into scoped, evidence-linked lessons and measures whether fresh workers benefit before sharing them. The initial customer is an engineering team running multiple coding or analysis agents against a common tool stack. The first environment is marimo notebook construction; later adapters could support another SDK or internal platform.

Do not claim nobody shares agent memory today. Shared memory, skills, retrieval, and evolving playbooks already exist. The product question is whether **tested, version-scoped lessons from other agents reduce repeated mistakes beyond documentation and unfiltered memory**.

### Product sentence

HERD is a shared learning layer for tool-using agents: it turns one agent's verified repair into a reusable lesson, tests that lesson on other workers, and distributes only the versions that earn admission.

### What changes

The worker's model weights, tool permissions, documentation access, and scoring rules stay fixed. Its retrieved skill context changes. The resulting claim is improved performance of the configured agent system through shared experience, not training a new foundation model.

## 3. The loop

1. Each of five learners receives marimo development tasks and the same frozen pool snapshot for that round.
2. A learner attempts a task in its own sandbox. The runner captures actual diagnostics and notebook behavior.
3. On failure, the learner repairs its notebook within a fixed budget.
4. A successful repair becomes a candidate lesson through a distillation step. Failed repairs remain evidence; they do not become advice simply because the explanation sounds plausible.
5. A curator checks scope, version compatibility, contradictions, leakage, and duplication. It cannot declare a lesson effective.
6. A trial runner compares fresh workers with and without the candidate added to the current pool, using new tasks and equal tools and budgets.
7. The statistical gate, fixed regression controls, and evidence-integrity checks decide whether to publish, reject, or quarantine the candidate.
8. At the next round boundary, all five learners receive the newly committed pool snapshot. They do not receive one another's conversations or completed notebooks.
9. After round three, freeze the final pool and evaluate independent fresh workers on untouched tasks.

A final broadcast makes the round-three pool available to the learner identities and final evaluators without inventing a fourth learning round.

## 4. Concrete marimo learning domain

Use a small but varied set of notebook requirements, not a single repetitive error puzzle. Each task has an input fixture, an explicit user requirement, public examples, and private behavioral probes.

| Track | Illustrative task | What the evaluator checks |
|---|---|---|
| Notebook structure | Repair a multi-cell data summary with colliding global names | Valid dependency graph, correct aggregate values, no duplicate-global failure. |
| Reactive input | Build a threshold slider that filters a table | Two or more private slider settings produce the correct rows and counts. |
| Dataflow and transformations | Build a derived dataset and summary that stay consistent | Changed input data yields the expected recomputation. |
| Forms and controlled execution | Submit user-selected settings to a computation | An edit does not count as a submission; committed values drive the required behavior. |
| Composition and deployment | Combine a widget, table, chart, and runnable app | App loads in a fresh process and remains correct under the required interactions. |

These are proposed task families. Every fixture must be validated against the pinned marimo version before agents encounter it. Library-specific rules live in the task adapter and docs snapshot, not in remembered assumptions.

### A suitable lesson

An illustrative lesson might say: “For independent temporary values in separate cells, use distinct globals or cell-local temporary names; do not redefine one global across cells.” Its applicability must be specific, and it must be tested on multiple notebook layouts. It is not automatically admitted because official documentation supports it.

### A useful deliberately false lesson

“Cells must be arranged top to bottom before their variables can be referenced” can serve as a clearly labeled poisoning control. Reordered-cell cases test whether HERD rejects advice that misunderstands the tool. Do not use the false rule as a real lesson in the public pitch.

## 5. Why the five-agent team matters

The five learners work on different primary tracks, so the training history is distributed. They rotate to non-origin tracks in later rounds. Repair and distillation are roles invoked within each learner's workflow, not five additional always-running agents. The curator, trial runner, gate, and evaluator have distinct responsibilities; most of those components are ordinary code.

What must be demonstrated is **cross-origin transfer**: a worker completing a new task using a lesson whose source was another learner. Showing five avatars or copying a file into five folders does not establish this.

Use provenance-aware retrieval in transfer trials: exclude lessons derived from the recipient's own training tasks where that comparison requires it. Final workers have no personal training history at all. Report received, retrieved, and actually evaluated lessons separately.

## 6. Headline experiment

**Headline:** fresh-worker task success with the final shared pool versus without it, under a fixed execution budget.

A task passes only when all required behavioral checks pass, the runner reports no integrity violation, and the attempt stays within its budget. Show raw passed/total counts and a paired difference with an interval.

The headline is intentionally simple. The underlying evaluation also needs:

- first-submission success and final success within the repair budget;
- model tokens, tool calls, elapsed time, and learning-system cost;
- regressions on clean tasks;
- no-pool, curated-documentation, raw-memory, and admitted-pool comparisons;
- per-track and cross-origin transfer;
- results for a deliberately false lesson;
- admission, rejection, and insufficient-evidence counts.

These are not extra products. They distinguish useful shared learning from more tokens, documentation injection, repeated attempts, or task-answer leakage.

## 7. The corrected demo

> “This worker has never seen the task or the earlier repair. It receives only lessons learned by other agents.”

Run two independent fresh sessions on a held-out task and identical fixture. One receives no shared lessons; the other receives the admitted pool through the same retriever and context budget policy. Neither can inspect the other's workspace or result.

If the no-pool arm fails and the pool arm succeeds, show the notebook responding correctly to a new UI input. Then reveal the small lesson and its origin/evaluation record. Do not paste the completed training notebook into the worker's context.

A separate same-worker retry can illustrate the mechanics, but label it as recovery and do not use it as the transfer evidence.

### Three-minute presentation

| Time | Visible evidence |
|---|---|
| 0:00–0:20 | A recorded development failure and the real diagnostic. State the repeated-learning problem. |
| 0:20–0:45 | Actual repair diff, distilled lesson, and its source learner. |
| 0:45–1:05 | Admission evidence and one clearly labeled rejected false lesson. |
| 1:05–1:30 | Five-agent, three-round replay with actual pool revisions. Show who contributed and who benefited. |
| 1:30–2:15 | Fresh-worker comparison: independent sessions, same new task, different lesson access. Run a bounded interaction live. |
| 2:15–2:40 | Held-out success counts, documentation baseline, and cost. Show measured results rather than promised gains. |
| 2:40–3:00 | Weave evidence link, marimo app, and the closing line. |

The comparison should be recorded from actual runs if both model attempts cannot finish inside the live slot. A fresh input interaction can remain live. Label replay and live content explicitly.

## 8. Sponsor story

| Tool | Role |
|---|---|
| W&B Weave | Traces attempts, repairs, distillations, retrieval, paired evaluations, and admission decisions; stores custom behavioral scores and links evidence to pool versions. |
| marimo | The tool learners master and the reactive application used to inspect learning, compare notebook behavior, and browse the pool. |
| W&B Inference | Model adapter for learner and distillation calls when compatible models and credits are available. Actual access and model IDs must be recorded. |
| ARIA | Analyzes real run summaries, explains failure concentrations, and proposes next-round development emphasis within frozen evaluation boundaries. Its analysis is stored and connected to a resulting experiment or curriculum decision. |
| molab | Hosted access to the control room or notebooks after persistence and package support are checked. |
| TypeSafe AI | Provider adapter and possible fixed-model replication when the onsite interface is confirmed; not a fabricated pre-integrated service. |

ARIA remains a full integration workstream, but its account availability must be represented honestly. The current automation documentation verifies monitor-triggered actions such as webhooks; it does not by itself verify a callable ARIA API. See the architecture's integration contract.

## 9. What makes this more than shared notes

The pool stores applicability, tested runtime versions, counterexamples, origin, executable probes, and admission evidence. Lessons can conflict, become obsolete, or consume context without helping. HERD measures those effects and supports revocation.

The novelty claim should be narrow: **evidence-based cross-agent skill sharing for a real tool workflow, with fresh-worker transfer and a complete admission record**. ACE and related systems provide prior art for lesson stores and incremental updates. A successful implementation can still be compelling without claiming a new learning algorithm.

## 10. Full-scope build commitment

The active design retains five learners, three rounds, statistical admission, trial isolation, versioned pool synchronization, retrieval, negative controls, observability, interactive UI, ARIA analysis, and multi-arm evaluation. Implementation should follow dependency order; that does not reduce the target scope.

Astra and Fable are treated as the user's named implementation collaborators. Their exact model capabilities or provider availability are not assumed. See [BUILD_PLAN.md](BUILD_PLAN.md) for ownership, interfaces, acceptance checks, and execution budgets.

## 11. Documents and evidence boundaries

- [ARCHITECTURE.md](ARCHITECTURE.md): components, schemas, execution, isolation, integrations, UI, failures, and testing.
- [GENERALITY.md](GENERALITY.md): lesson admission, statistical assumptions, transfer, composition, and revocation.
- [BUILD_PLAN.md](BUILD_PLAN.md): complete work packages and verification plan.
- [protocol.json](protocol.json): reviewable experiment defaults, not results.
- [verify_architecture.py](verify_architecture.py): checks protocol arithmetic and selected invariants; not proof that an application exists or is secure.
- [Historical verifier-HERD](archive/verifier-herd-v1/README.md): retained comparison material.
- [Historical DOJO](../astra.md): earlier refund-recovery direction.

## 12. Claim discipline

Say “the configured agent improved on these held-out tasks” only after measuring it. Say “statistical evidence under this protocol” rather than “PACE proves the lesson.” Say “shared tool-specific experience” rather than “every agent everywhere is smarter.” If no candidate earns admission, the control room must show that honestly; the architecture does not promise a growing pool in every run.

The final product question is simple: **can an agent complete useful new work better because other agents already paid the cost of learning the tool?**
