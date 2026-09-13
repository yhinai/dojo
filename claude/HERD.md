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

## 7. The demo

Three minutes, strictly enforced, one slide. The demo opens on the **problem in a single image**, not on the system. Every beat below names the artifact it reads, whether it is recorded or live, and what to do if the artifact does not exist. Nothing is promised before it is measured; recorded material is labeled recorded; the illustrative task is labeled illustrative.

### The hook

Five agents, five separate sessions, the same tool, the same mistake — stacked on one screen. Then one sentence.

> **"Five agents. Same tool. Same mistake. None of them can tell the others."**

That image is the entire problem statement, and it is *true of every multi-agent deployment in this room*. It takes eight seconds and requires no explanation of HERD.

### Beat sheet

| Time | Beat | On screen | Source | Fallback |
|---|---|---|---|---|
| **0:00–0:08** | **The hook.** Say the line. Nothing else. | Five learner panels from round one, each showing the same marimo diagnostic on a structurally similar task (the duplicate-global collision, or whichever failure actually recurred). Actual diagnostics, actual timestamps, labeled *recorded, round 1*. | Round-1 event log; the control room's learner cards | If fewer than five learners hit the same failure, show the largest cluster ARIA identified ("3 of 5 agents, same failure family") — still the same sentence, with the true number. |
| **0:08–0:30** | **One of them figured it out.** | Learner 2's repair diff — before/after, a few lines — then the distilled lesson card: trigger, instruction, *does not apply*, origin. | `LessonRevision` record + repair diff from the event log | If no lesson was distilled, show the repair diff alone and say the distillation step honestly did not fire. |
| **0:30–0:50** | **The pool didn't just take its word for it.** | The gate view for that candidate: wins / losses / ties, E climbing past the threshold, the regression controls all green, **and right beside it the rejected false lesson** — *"cells must be ordered top to bottom"* — with its stage of rejection named. | `GateState` + `TrialRecord`; the labeled poisoning-control record | If no candidate crossed the gate, show the closest stream with its E value and say "insufficient evidence — it stayed in quarantine." That is the system working. |
| **0:50–1:05** | **Round timeline.** Fifteen seconds, sped up, labeled *recorded*. Three rounds, pool revisions appearing, who contributed, who received. | Three-round timeline panel, `PoolSnapshot` diffs | — |
| **1:05–2:05** | **THE LIVE BEAT — split screen, two fresh workers.** *"This worker has never seen the task, the repair, or the other agents. Left: no lessons. Right: only lessons other agents learned."* Same held-out task, same fixture, same budget, independent sessions. Show the two notebooks side by side. Then **drag the slider on the right-hand notebook live** — the table refilters correctly. | §4.3-style fresh-worker pair on a *Demonstration*-partition task; live `preview_notebook` on the passing arm | **Recorded pair + live probe.** If two model attempts can't finish in the slot, play the recorded pair (labeled) and run only the slider interaction live — the interaction is the part that proves the notebook actually works. If the pool arm failed on this task, say so and show the aggregate instead. Never swap in a different task after the fact without saying so. |
| **2:05–2:35** | **The numbers.** *"That was one task, chosen to be illustrative. Here is all of them."* | Final four-arm panel: passed/total per arm, the paired admitted-pool-minus-no-pool difference with its interval, tokens per arm. **Say the curated-docs number out loud** — it is the baseline a skeptic reaches for first. | `ExperimentReport` | If the lift is zero or negative, show it as zero or negative. Then say what the run *did* establish: the admission machinery, the rejected false lesson, the cost. |
| **2:35–2:50** | **Sponsors in one breath.** *"Every attempt, repair, trial, and admission is a Weave evaluation row; the control room you're looking at is a marimo notebook; ARIA read the round summaries and flagged the failure cluster you saw at the top."* | One Weave evaluation page, the control room itself, the stored ARIA report | If ARIA access never materialized, drop the clause. Do not describe an integration that did not run. |
| **2:50–3:00** | **Close.** Return to the five-panel image from the hook, now with the pool revision number next to each learner. | Learner cards, final state | — |

> **"One agent struggles. Every agent learns."**

### The one slide

Title: **HERD — One agent struggles. Every agent learns.**
Body, four lines:
1. Five learners · three rounds · marimo · verified repairs → scoped lessons
2. Lessons **earn** the pool: fresh paired trials, sequential gate (α = 0.05), regression controls, false-lesson rejection
3. Headline: fresh-worker success, admitted pool vs no pool — *[the real number, with n and interval]*
4. Built on: marimo, W&B Weave (Evaluation + Leaderboard), W&B Inference, ARIA. Reused: ACE lesson format, PACE gate construction.

Line 4 is deliberate. Naming foundations reads as maturity and pre-empts "what did you build?"

### Pre-answered questions

| Question | Answer, cold |
|---|---|
| *"Isn't this just more context?"* | "Four arms, same envelope cap. Curated docs got the same 2,000 tokens; raw memory got the same 2,000 tokens. Here are the three numbers side by side." |
| *"How do you know the lesson caused it?"* | "We never credit a lesson from an episode that happened to retrieve it. Only paired fresh-session trials, with and without, count as evidence — and it has to clear a sequential test that bounds false admission at 5%." |
| *"What if the model already knows marimo?"* | "Then the lift is zero and we show zero. We calibrated task families first so the worker measurably fails; where it didn't, that family isn't in the headline." |
| *"What did you build versus reuse?"* | Point at slide line 4. "The lesson format is ACE's, the gate construction is PACE's. The broker isolation, the behavioral oracle, the paired trial service, the pool transactions, the four-arm evaluation, and the control room are ours." |
| *"Would it catch a bad lesson you didn't plant?"* | "The regression controls are behavioral — a lesson that breaks clean tasks fails them regardless of why. The planted false lesson tests that path; the fixed controls run on every candidate." |
| *"Why only five and three?"* | "Because every admission is 64 fresh paired episodes and we report every one. Five and three is what we can run honestly before 1pm, not what the architecture caps at." |

### What must be true for the demo to exist

Listed in dependency order; each is a line in the build plan's demo work package.

1. A round-one recording exists with at least three learners hitting the same failure family — or ARIA's cluster report, if fewer.
2. At least one repair diff and its distilled lesson record.
3. At least one gate stream with a visible E trajectory, and the rejected false-lesson record with its named rejection stage.
4. A *Demonstration*-partition task with a recorded fresh-worker pair, and a live-launchable copy of the passing notebook.
5. The final four-arm report, whatever it says.
6. The control room running in read-only demo mode, with refresh disabled from triggering paid calls.
7. A backup screen recording of the whole three minutes, under two minutes long, for the submission form.

## 8. Sponsor story

| Tool | Role |
|---|---|
| W&B Weave | Traces attempts, repairs, distillations, retrieval, paired evaluations, and admission decisions; stores custom behavioral scores and links evidence to pool versions. |
| marimo | The tool learners master and the reactive application used to inspect learning, compare notebook behavior, and browse the pool. |
| W&B Inference | Model adapter for learner and distillation calls when compatible models and credits are available. Actual access and model IDs must be recorded. |
| ARIA | Analyzes real run summaries, explains failure concentrations, and proposes next-round development emphasis within frozen evaluation boundaries. Its analysis is stored and connected to a resulting experiment or curriculum decision. |
| molab | Hosted access to the control room or notebooks after persistence and package support are checked. |

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
