# HERD v2 — Full-scope build and verification plan

> Target: the complete architecture in [ARCHITECTURE.md](ARCHITECTURE.md), retaining five learners, three rounds, cross-agent trials, PACE, skill pooling, retrieval, poisoning controls, Weave, the marimo control room, ARIA analysis, and final multi-arm evaluation.
>
> Astra and Fable are the user's named implementation collaborators. This plan allocates responsibilities; it does not claim that either collaborator has already executed the work or that a particular unlisted model is available.

## 1. Build strategy

Parallelize along ownership boundaries, not by asking both builders to independently create the whole application. Establish shared schemas, statuses, protocol fields, event IDs, and adapter interfaces first. Integrate on a real task early, then fill out all five tracks and three rounds.

Dependency ordering is not a scope cut. A partially working loop is an integration milestone; the completion checklist remains the full system. A failed provider or sponsor prerequisite is an explicit blocker, not a reason to quietly remove a feature from the definition of done.

## 2. Responsibility split

| Workstream | Primary owner | Review owner | Deliverable |
|---|---|---|---|
| Core schemas and protocol | Astra | Fable | Shared typed contracts and example messages. |
| Task adapter, sandbox, behavioral oracle | Fable | Astra | Real notebook execution and interaction checks. |
| Learner, repair, distillation | Astra | Fable | A verified repair becomes a candidate package. |
| Curator and retrieval | Astra | Fable | Version-aware context selection and conflict handling. |
| Sequential gate and pool transactions | Astra | Fable | Persisted evidence, guarded admission, atomic snapshots. |
| Weave and evidence capture | Fable | Astra | Authentic trace-to-result provenance. |
| Five-learner scheduler and three-round barriers | Astra | Fable | Resumable full experiment. |
| marimo control room | Fable | Astra | Reactive evidence UI with idempotent actions. |
| ARIA and provider adapters | Fable | Astra | Real analysis workflow and model-access checks. |
| Final comparisons and reporting | Astra | Fable | Four-arm fresh-worker results and clustered summaries. |
| End-to-end review and demo | Both | Cross-review | Measured, reproducible presentation. |

No builder should modify the other's contract without a documented version change. Use a shared contract module, small integration commits, and fixtures with stable hashes.

## 3. Preflight: dependencies that cannot be assumed

Before scheduling paid runs, establish:

- the exact marimo and Python versions;
- compatible dependency versions and an immutable image digest;
- a working container engine and controlled browser connectivity;
- available model IDs, provider limits, price information, and a spending cap;
- a W&B project with working trace writes and reads;
- ARIA access, account prerequisites, and the actual supported interface;
- whether molab can run the intended control room and preserve required artifacts;
- sufficient CPU, RAM, ports, and disk for ten trial workers plus the controller.

Record the results in an execution manifest. The architecture's protocol is reviewable with these fields unresolved, but the real experiment must refuse to start while critical runtime, model, or budget fields are missing.

## 4. Contract package

Implement typed models for `TaskManifest`, `WorkerBudget`, `AttemptRecord`, `BehaviorResult`, `LessonDraft`, `LessonRevision`, `PoolSnapshot`, `TrialBinding`, `PairOutcome`, `GateState`, `RunEvent`, and `ExperimentReport`.

Define all terminal states centrally. Unknown values must fail validation rather than silently default to success. Monetary values should preserve units and provider provenance; unavailable prices are not zero.

Create example messages covering:

- successful notebook submission;
- incorrect interaction despite successful startup;
- an invalid infrastructure pair;
- a candidate win, loss, and tie;
- insufficient evidence;
- a regression veto after threshold crossing;
- a pool compare-and-swap conflict;
- runtime incompatibility;
- a final report with no admitted lessons.

These examples are fixtures for implementation contracts, not measured demonstrations.

## 5. Task and oracle work package

Build and validate the five tracks in the architecture. Each track needs multiple notebook templates and input fixtures, not just renamed copies of one notebook.

Every task template must include a real reference solution, public test examples, private behavioral probes, and a known bad implementation that fails for the right reason. Do not make a private test dependent on a specific implementation style if the user-visible behavior can be achieved another valid way.

For a widget task, the evaluator should drive actual controls and inspect recomputed outputs. For a form task, verify the difference between changing a draft value and submitting it. For a composition task, launch in a fresh process and test the required combined behavior.

Deliver an oracle validation report listing runtime hash, task/template IDs, reference-pass outcomes, and negative-control failures. A task whose reference fails is a fixture bug and must be fixed before being used to judge an agent.

## 6. Execution and isolation work package

Implement a broker that starts containers, submits notebook content, invokes structural checks, serves docs queries, starts candidate apps, and dispatches public/private probes through separate interfaces.

The learner should never receive a filesystem path that reaches the private evaluator. Test path traversal, symlinks, artifact names, and attempted service access. Verify no provider or W&B secret appears in candidate environment variables, mounted files, or tool outputs.

Use explicit process and wall-time limits. Kill all descendant processes on episode completion and collect artifacts before destroying the sandbox. Repeated runs must not inherit a previous notebook server, cached outputs, or other arm's workspace.

## 7. Learning work package

Implement the bounded task attempt first, then repair, then distillation. Distillation requires a recorded passing repair. The output schema must include scope and a counterexample condition; generic “be careful” advice is not sufficient.

A learner's role identity persists for provenance, but each task's execution context should be clearly defined. If development conversations persist within a round, record that behavior and never give final workers the same history. The primary transfer experiment uses fresh workers regardless of development memory.

Prefer fresh task sessions with only the round pool and bounded own-task repair history so cross-agent learning is attributable. Any personal memory feature must be versioned and tested separately rather than silently added.

## 8. Curator and retrieval work package

Implement deterministic exact-deduplication and size/version checks before semantic analysis. Keep task-answer leakage reports reviewable. Store rejected drafts and reasons rather than deleting them.

For the primary experiment, use the architecture's fixed tag-based ranker with stable ties. Retrieval is part of the treatment: evaluate actual selected context, including truncation and displacement. Test that incompatible or retracted lessons cannot appear in the envelope.

Build a conflict browser for the UI. Curator confidence is advisory; measured behavior determines whether an instruction is useful.

## 9. Statistical and pool work package

Implement gate updates in log space and persist them transactionally with unique pair IDs. Bind every update to immutable hashes for candidate, incumbent, retriever, model, runtime, docs, and sampler.

Required reference checks include:

- five all-win observations cannot pass a threshold of 300;
- fourteen all-win observations remain below it;
- fifteen all-win observations cross it;
- ties do not change evidence;
- losses reduce evidence;
- restart reproduces the same state;
- duplicate pair IDs do not count twice;
- changed candidate/incumbent bindings are rejected;
- regression veto overrides threshold crossing;
- the 15 slot allocations sum to the registered total alpha;
- an exhausted stream is quarantined, not automatically accepted.

The checked arithmetic does not establish the statistical assumptions in a live sampler. Test task freshness and arm isolation separately.

Pool writes use one service and compare-and-swap on the expected parent. An admitted package has an immutable report. Source agents receive no pool-write tool.

## 10. Scheduler work package

Implement five learner identities, three task assignments per identity per round, and three round barriers. All learners in a round receive the same starting pool hash. Candidate processing uses a fixed order, not whichever result looks most promising.

Checkpoint every completed episode, reserved candidate slot, evidence update, and pool commit. A restart must resume rather than multiply evidence. If a learner fails, keep its slot and episode status visible; do not relabel a four-agent run as a five-agent run.

Training and trial execution use different queues sharing a global resource reservation manager. Prevent ten trials plus five learners from exceeding the actual machine's capacity. The configured concurrency is a ceiling, not an obligation to oversubscribe.

## 11. Evidence and sponsor work package

Record execution events locally, then upload to Weave through an idempotent outbox. Implement actual custom scorers and attach the resulting IDs to gate records. Verify that a displayed lesson can be followed backward to its repair and forward to its fresh-worker trial.

ARIA must analyze actual experiment summaries. Capture its report and connect it to a real development-only curriculum decision. If the required automated trigger is not available, implement the supported interface with honest manual initiation and label it as such. Do not claim a nonexistent API or fabricate an analysis.

TypeSafe and alternative provider support should use the same gateway interface. A model-family replication is a new run with its own model binding; it is not mixed into the primary worker comparison.

## 12. Interface work package

Build the complete control room specified in the architecture. Use actual records to populate every panel. During development, synthetic fixtures must carry a visible “fixture” label and cannot be exported as measured results.

Connect learner cards, round timeline, pool browser, notebook comparison, gate details, final metrics, poisoning controls, and ARIA analysis. Make loading, empty, insufficient-evidence, and failure states first-class views.

Separate read-only filters from actions that start paid work. A refresh or slider change cannot submit model calls. Start/resume controls require idempotency keys and display the associated experiment ID.

## 13. Final experiment work package

Freeze the final pool, curated-doc summary, raw-memory selection rule, retrieval configuration, worker model, and task manifest before scoring. Run all four arms on the same tasks using new workspaces and conversations.

The reference plan is 60 tasks from 12 final families, four arms, and three worker repeats. Report task-family clustered uncertainty and per-family counts. Preserve raw paired outcomes so another person can recompute the comparison.

Measure first-submission success, final success within budget, tool calls, tokens, time, and total learning cost. Compute the primary pool-minus-no-pool difference and include the stronger documentation and memory comparisons. A pool that merely ties documentation has not demonstrated superior information selection.

A separate leave-one-origin-out analysis can test whether benefits persist when a recipient cannot retrieve lessons from its own source track or identity. It is supplementary and must have a declared dataset; do not carve out a flattering subset after seeing results.

## 14. Work sequencing without reducing scope

| Stage | Parallel work | Integration exit |
|---|---|---|
| Contracts and preflight | Astra defines schemas/protocol; Fable validates runtime and notebook runner | One reference task can be scored through the shared contract. |
| First real learning chain | Astra implements attempt/repair/distillation; Fable implements behavioral checks and Weave | Actual failure → passing repair → quarantined lesson with trace. |
| Admission and pool | Astra implements trials/gate/pool; Fable implements controls and UI evidence views | A real candidate reaches a justified decision; no fabricated acceptance. |
| Full population | Astra implements scheduler; Fable completes all task tracks and visual panels | Five learners finish a round with consistent snapshot exposure. |
| Full experiment | Three rounds, candidate trials, integration completion | P_3 frozen with all decisions and costs accounted for. |
| Transfer and presentation | Astra runs four-arm analysis; Fable assembles the actual demo and ARIA report | Reproducible final report and three-minute demonstration. |

Estimate duration from measured episode cost and latency during preflight. Do not promise the full experiment finishes merely because code generation is fast. Persist progress so an interrupted run can continue with its original scope and evidence intact.

## 15. Mandatory tests

### Unit/contract tests

Schema rejection, gate arithmetic, duplicate evidence, hashing, deterministic retrieval, incompatible versions, token-envelope truncation, budget reservations, and pool compare-and-swap.

### Integration tests

Notebook lifecycle, actual widget interaction, reference/negative fixture checks, private-probe isolation, runner event capture, Weave outbox behavior, and idempotent UI controls.

### End-to-end tests

Five-learner assignment; round snapshot consistency; real candidate admission or rejection; three-round resume; final-arm isolation; false-lesson control; final report joins; and complete trace-to-lesson-to-outcome provenance.

### Statistical protocol tests

Task ID uniqueness, sampler identity binding, no final data in candidate contexts, no evidence reuse after content/comparator changes, correct alpha-slot accounting, and explicit uncertainty labels. Monte Carlo checks under simulated null/alternative streams may catch implementation mistakes, but they do not validate the real world's sampling assumptions.

## 16. Completion checklist

- [ ] Five learner identities and all three rounds implemented and exercised.
- [ ] Five task tracks contain validated reference and negative fixtures.
- [ ] Model/runtime/docs versions and prices are pinned in an execution manifest.
- [ ] Local attempts and bounded repairs produce authentic evidence.
- [ ] Candidate lessons contain scope, origin, exclusions, and runtime compatibility.
- [ ] Curator, conflict handling, retrieval, and context caps are implemented.
- [ ] Fresh paired admission trials run under immutable bindings.
- [ ] PACE gate, 15-slot alpha allocation, quarantine, and veto behavior are tested.
- [ ] Pool synchronization, composition checks, revocation, and resume work.
- [ ] Candidate code cannot read or modify evaluator data or credentials.
- [ ] Weave traces and custom scores connect to all reported decisions.
- [ ] marimo control room presents all required panels and authentic empty/failure states.
- [ ] ARIA analyzes real data and its contribution is recorded, or its integration blocker remains explicitly open.
- [ ] Four-arm fresh-worker comparison is executed with raw results and cost reporting.
- [ ] Same-session retry is not presented as isolated cross-agent transfer.
- [ ] Demo uses actual outcomes and clearly distinguishes replay from live behavior.
- [ ] Research attribution and reused components are documented.
- [ ] Submission requirements, team surveys, repository access, and recording are complete.

## 17. What this revision delivers

This revision delivers the product decision, complete architecture, admission specification, build plan, reference protocol, and a focused protocol checker. It does not deliver the runtime application, provider credentials, ARIA account access, or measured gains. Those are the implementation work described above.
