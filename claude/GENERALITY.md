# HERD v2 — When does a lesson deserve to spread?

> Active shared-skill admission specification. This replaces the earlier verifier-patch generality design. [Architecture](ARCHITECTURE.md) · [Reference protocol](protocol.json).

## 1. The precise question

A lesson is worth sharing when adding it to the current retrieval-enabled pool improves fresh-worker task outcomes in a declared applicability domain, without failing the registered regression and integrity controls.

This is a statement about a **particular lesson version, worker configuration, retrieval policy, tool runtime, and task distribution**. It is not an intrinsic property of a sentence. A correct sentence can be redundant, poorly retrieved, too broad, or harmful through context displacement.

Distinguish:

- **Truth:** is the technical advice supported by the tool's behavior or documentation?
- **Applicability:** does the advice apply to this task and runtime?
- **Utility:** does injecting it improve a worker's outcomes?
- **Transfer:** does utility appear on tasks and workers outside the originating experience?
- **Composition:** does it remain useful alongside existing lessons?

A source citation helps establish truth. It cannot establish all five properties.

## 2. The candidate package

A package contains one or two related procedural bullets, scope tags, a runtime hash, exclusion conditions, origin learner/task IDs, repair evidence references, and a content hash. The package is the unit of statistical evaluation.

If two bullets are admitted together, report that the package helped; do not pretend the experiment isolated each bullet. Follow-up ablations can later split or remove redundant statements.

The worker sees instructions and short generic examples. It does not receive private evaluation labels, whole source notebooks, source-specific outputs, or the source agent's conversation.

## 3. Admission pipeline

```text
Verified local repair
  → Distilled lesson hypothesis
  → Schema/version/scope checks
  → Leakage and contradiction checks
  → Development probes
  → Freeze package + incumbent + protocol
  → Fresh paired transfer stream
  → PACE-style threshold + regression/integrity checks
  → Atomic pool version or explicit quarantine/rejection
```

Development probes may be used to improve a draft. Once statistical evaluation starts, any content edit starts a new candidate slot and a new evidence stream. Failed streams cannot be silently reset until they get lucky.

A lesson drawn from an unsuccessful local repair cannot enter this path as a demonstrated repair lesson. It may remain a research hypothesis outside the active pool.

## 4. What counts as a pair

For pair i, create two independent fresh worker sessions on the same newly drawn task and fixture:

- **Control:** current pool P.
- **Treatment:** P plus candidate L through the same retriever.

The model, tool permissions, public docs, time/action/token limits, runtime, and evaluator are identical. Each side starts from a clean workspace and empty conversation. Randomize which executes first. Each side may use the same permitted local repair budget.

A fixed task identity pairs the outcomes. Identical provider seeds do not guarantee identical model sampling, and are not required for the comparison. Record them when supported. Changes in model version or provider configuration invalidate the stream's frozen configuration.

Let treatment success be T_i and control success be C_i:

| T_i | C_i | Evidence |
|---:|---:|---|
| 1 | 0 | Win for candidate |
| 0 | 1 | Loss for candidate |
| 1 | 1 | Tie: both succeed |
| 0 | 0 | Tie: both fail |

Invalid infrastructure pairs are not evidence. Candidate-caused failure is a real zero. Do not remove disappointing outcomes as infrastructure noise.

## 5. Scope of the null hypothesis

The reference update assumes that under the no-improvement null, each discordant pair is conditionally no more likely to favor treatment than control, given earlier evidence. Under that assumption, the evidence process supports a bound on erroneous promotion.

For binary task success, the difference in success probabilities is the probability of a treatment-only success minus the probability of a control-only success. This connects the paired comparison to success lift in the declared sampling distribution.

To make the conditional assumption plausible:

1. Freeze candidate, comparator, retriever, model, runtime, and task distribution before sampling.
2. Draw new task instances using the registered sampler, not a search for cases the candidate is known to win.
3. Never replay a deterministic result as a new observation.
4. Do not change the candidate based on partial trial outcomes.
5. Do not prioritize tasks after learning their likely paired result.
6. Record any drift, dependency, or reuse that undermines the sampling model.

Repeated templates can limit external diversity even with independently sampled fixtures. The final report must state the family coverage and use appropriate clustered summaries. Statistical validity inside a sampler is not proof that the sampler represents all real work.

## 6. PACE-style evidence update

For discordant outcomes, define w_i = 1 for a win and 0 for a loss. With lambda fixed at 0.5:

```text
E_0 = 1
E_i = E_(i-1) × [1 + 0.5 × (2w_i − 1)]

win:  E ← E × 1.5
loss: E ← E × 0.5
tie:  E unchanged
```

Use log space in implementation. Persist wins, losses, ties, pair IDs, and the full stream binding alongside log(E).

The PACE paper motivates a per-candidate sequential acceptance test and explicitly limits its claim to the conditional paired null. It does not certify universal lesson correctness or automatically control an entire adaptive colony. [PACE primary source](https://arxiv.org/html/2606.08106v1)

## 7. Error allocation: executed gate versus documented bound

The full run has five learners × three rounds = **15 reserved candidate slots**. Two error policies are defined; one is executed, the other is reported.

### Executed gate — per candidate

```text
alpha_candidate = 0.05
threshold       = 1 / alpha_candidate = 20
```

This is the guarantee the PACE construction actually provides: for a fixed candidate/comparator/protocol binding, the probability of a false promotion is at most 0.05 under the conditional paired null, under optional stopping.

### Documented bound — familywise across 15 slots

```text
alpha_total = 0.05
alpha_slot  = 0.05 / 15 = 1 / 300
threshold   = 300
```

A union bound limits the probability of *any* statistical false promotion across the 15 comparisons to 0.05. It is reported alongside every admission decision (the UI shows whether each admitted candidate would also have crossed 300), but it is **not** the executed gate, for a reason that is quantitative, not cosmetic:

| True lift (control → treatment) | P(admit) at 300 | P(admit) at 20 |
|---|---|---|
| +10pt (40 → 50) | 1.9% | 18.6% |
| +20pt (40 → 60) | **15.8%** | **54.9%** |
| +30pt (40 → 70) | 55.0% | 88.7% |
| +40pt (40 → 80) | 91.9% | 99.3% |
| null (no effect) | 0.07% | 3.1% |

(Monte Carlo, λ = 0.5, 64 pairs, 20,000 trials per cell.) At threshold 300 a lesson with a large real effect is admitted about one time in six; a run at that setting most likely ends with an empty pool and no transfer to show. At threshold 20 the measured null false-admission rate stays under its 5% bound. Neither bound covers oracle bugs, distribution mismatch, dishonest capture, leakage, or unmeasured regressions.

### Evidence feasibility at the executed gate

- 5 consecutive wins: E = 7.59, insufficient.
- 7 consecutive wins: E ≈ 17.09, insufficient.
- **8 consecutive wins: E ≈ 25.63, crosses 20.**

Each loss multiplies E by 0.5 and costs roughly 1.7 wins of progress; ties contribute nothing. A candidate receives up to **64 fresh pairs**. A weak improvement can still remain unadmitted, and that outcome is reported as `INSUFFICIENT_EVIDENCE`, not hidden.

Unused slots are not reassigned after seeing evidence. Rewording a lesson, changing its scope, replacing its comparator, or rerunning after rejection uses a new reserved slot. The fixed bet λ = 0.5 is a known limitation on binary outcomes; an adaptive betting scheme from the e-process literature would raise power further and is a documented follow-up, not a mid-run change.

## 8. Admission decision

The sequential threshold is necessary, not sufficient. A candidate can activate only when:

1. Its schema, runtime, and evidence binding remain valid.
2. E reaches the registered threshold.
3. All required fixed integrity and poisoning controls pass.
4. The candidate pool introduces no failure on the registered must-pass regression controls relative to their validated reference outcomes.
5. The pool-service compare-and-swap confirms the incumbent hash is unchanged.
6. The required evidence artifacts exist and their hashes match.

The controls are a finite release policy, not an inferential proof of zero harm. Repeatedly inspected regression cases are not an untouched final set.

If the threshold is not crossed at the maximum pair count, return `INSUFFICIENT_EVIDENCE`. That does not establish that the lesson is useless. If a must-pass control fails, return `REJECTED_REGRESSION` with the failing check. A structural violation returns a different named reason.

The primary gate tests success rather than token efficiency. If a candidate only reduces tokens while preserving success, this experiment can report that as secondary evidence; do not promote it through an undeclared cost-only rule. A future cost-focused gate needs its own endpoint and protocol.

## 9. Fair strong baselines

The final four-arm experiment includes:

- no shared memory, with normal documentation access;
- a fixed curated documentation quick-reference;
- unfiltered development memory selected by a frozen rule;
- the statistically admitted shared pool.

The docs baseline challenges the proposition that ordinary documentation is enough. The raw-memory baseline challenges whether admission and distillation improve on simply retaining experience. The no-pool comparison answers the requested headline.

All arms have the same worker capabilities and overall budgets. The memory-bearing arms have equal envelope caps. Compare actual resource use; do not mistake a greater context allowance for a learning algorithm.

## 10. What “fresh agent” means

A fresh worker has:

- a new conversation;
- a new workspace and notebook process;
- no cached source repair or completed training artifact;
- the same fixed base model and tool access as its comparator;
- only its assigned context envelope;
- no access to another arm's outputs.

It is an independent session, not a newly trained model. Explain that distinction plainly.

The source learner can have failed and repaired a related task. The recipient must not receive that exact completed solution. For stronger transfer, hold out notebook templates and combine learned capabilities in new ways. Do not equate changed variable names with a new problem family.

## 11. The demo correction

The proposed sequence “fresh agent fails, then give it the pool and retry the same task” demonstrates assisted recovery, but the second attempt also benefits from its own failure. It cannot isolate transfer from other agents.

Use fresh A without the pool and fresh B with the pool. Both receive the same new task and equal budgets. B never sees A's attempt. A side-by-side replay of actual outcomes is acceptable, followed by a live input perturbation showing that the successful notebook is functional.

If both pass, show the result and costs. If B fails, do not claim the lesson transferred. A demo task selected because it produces a dramatic contrast must be labeled illustrative; the aggregate held-out comparison is the main evidence.

## 12. Poisoning and contradiction controls

Keep a separate labeled suite of false or overgeneralized candidate lessons. It is not generated evidence and must not be attributed to a spontaneous learner failure.

Examples include:

- the false top-to-bottom cell-ordering rule;
- advice to suppress an exception instead of fixing the computation;
- advice to hardcode an observed output;
- a correct rule applied to an incompatible runtime;
- a context-heavy redundant lesson that displaces useful advice;
- two individually plausible lessons with conflicting applicability.

Use these to test the curator, trial service, and regression controls. A poisoning control that is rejected by a schema rule tests schema enforcement; it does not establish that the statistical gate detected harmful semantics. Label the stage responsible for each rejection.

## 13. Composition, merge, and revocation

Two accepted lessons are not automatically useful together. Retrieval ordering and context limits can alter behavior. Evaluate each candidate as a delta to the current full pool. Do not merge paraphrases into an admitted lesson silently: a content-changing merge creates a new version and candidate comparison.

For exact-content duplicates, add provenance links without claiming new statistical evidence or changing the runtime instruction. Near duplicates are a curator recommendation, not an automatic semantic merge.

If development monitoring reveals a regression, quarantine the implicated lesson or composite and create a new pool revision. If attribution is uncertain, retract the composite revision rather than falsely blaming a single bullet. Restore the last known compatible snapshot while investigating.

Final test data remain read-only evidence for the closed experiment. Any fixes prompted by those results belong to a new experiment.

## 14. Helpful and harmful accounting

Maintain four separate concepts:

- **Exposure:** the lesson was present in a pool snapshot.
- **Retrieval:** the lesson was actually injected for a task.
- **Outcome association:** a retrieved episode succeeded or failed.
- **Paired effect evidence:** outcomes differed under a defined with/without comparison.

ACE-style helpful/harmful counters should refer to the last category when used as effectiveness claims. Association counters can be displayed, but must not be renamed causal benefit. A package trial cannot identify each member's independent effect without ablation.

## 15. Limits and failure conditions

- A powerful worker may already know the relevant marimo rules. The measured effect can be zero.
- A correct lesson can fail to transfer because its trigger is unclear or retrieval misses it.
- A fresh sampler can still be unrepresentative.
- A finite suite can miss an incorrect behavior.
- Statistical conservatism can keep a useful lesson quarantined.
- More agents increase the candidate supply and evaluation bill; they do not guarantee a better pool.
- A three-round result does not establish indefinite improvement or stability across future versions.

These limitations do not make the idea bad. They identify the conditions the complete system should expose, measure, and handle rather than hide.

## 16. What the gate display may say

Allowed: “Candidate admitted after these paired trials and registered checks; applies to this runtime and task distribution.”

Not supported: “Proven correct,” “helps every agent,” “95% safe,” “no future regressions,” or “five agents voted yes, so statistically verified.”

The point is to turn a plausible lesson into accountable evidence, without making a stronger claim than the experiment can support.
