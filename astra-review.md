> **Historical DOJO proposal:** The active direction is shared-skill HERD, specified in [claude/HERD.md](claude/HERD.md) and [claude/ARCHITECTURE.md](claude/ARCHITECTURE.md). This file is preserved as research and decision history.

# Devil's-advocate review of DOJO

**Review date:** September 13, 2026.

**Reviewed document:** [astra.md](astra.md).

**Method:** Independent delegated devil's-advocate review plus a separate coordinating-agent review of the written design. This is a conceptual and specification audit. No prototype was executed and no empirical claim was verified in this review.

## Verdict

DOJO is a complete concept and a substantial project brief, but it is not yet a fully settled implementation specification or a validated opportunity. It is reasonable to build a small experiment first. It is premature to describe its learning benefit, multi-agent advantage, or production usefulness as verified.

## Findings

### 1. The learned-repair advantage could disappear under an ordinary baseline

**Importance:** Potentially fatal to the claimed advantage; already acknowledged but unresolved.

**References:** Sections 3, 6, 7, 11, and 20.

The public contract already describes stable operation IDs, authoritative status, bounded polling, and safe retries. A short handwritten routine may handle the entire registered failure family. Restricting generated changes to a small state machine makes the system tractable, but also makes this objection stronger.

**Resolution:** Run the competent worker and handwritten routine before building the full dashboard. Then test a generated candidate on matched cases. If the manual routine wins, report that result. DOJO may still be a useful verification tool, but learned superiority is unproven. A generated routine that improves the original worker and ties the handwritten routine can still demonstrate automated repair; it does not establish superior reliability or lower engineering cost. Do not weaken the baseline or add arbitrary fault complexity to force a win.

### 2. The worker/routine control boundary is undefined

**Importance:** Implementation blocker; fixable.

**References:** Sections 5, 8, 9, and 10.

The document says the worker gets an artifact reference and that the interpreter executes calls and terminal decisions. It does not settle who invokes the routine, which observations trigger it, what state is transferred, or whether the worker can bypass or override its result. Different implementations would test different hypotheses.

**Resolution:** Choose one explicit contract before implementation. For example, a fixed dispatcher invokes the active routine on a documented ambiguous refund response; supplies public observations, retained operation ID, and remaining budget; and receives either a supported terminal result or a return-to-worker result. Use that dispatcher in all experimental arms. Describe the learned change as an agent-authored recovery program in the deployed system, not a change to model weights or proof that the worker's reasoning improved.

### 3. Virtual waiting may give the learned arm an extra capability

**Importance:** Threat to comparison validity; fixable.

**References:** Sections 6, 9, and 11.

The interpreter can advance virtual time, but the public worker tool list contains no explicit wait mechanism. A baseline that cannot advance time or make the same bounded polling choices may fail for reasons unrelated to learning.

**Resolution:** Specify one clock policy for all arms. Every arm must have equivalent access to permitted waits and recovery operations. Charge the same step and timing budgets. If execution is deterministic within the routine, distinguish those steps from LLM decisions in the trace.

### 4. Acceptance criteria are described but not finalized

**Importance:** Implementation and evaluation blocker; fixable.

**References:** Sections 10, 11, and 16.

The primary measure, minimum lift, clean-task floor, candidate cap, and spend cap remain configurable placeholders. Moreover, 'no new critical violations' can permit an existing violation to persist.

**Resolution:** Freeze a small protocol before examining candidates. Define correct-disposition counts as a possible primary measure, enumerate absolute disqualifiers, define clean-case regression rules, and set search and spend limits. Distinguish relative improvement from eligibility for release. Zero observed critical violations is still finite-sample evidence, not a safety guarantee.

### 5. The multi-agent contribution is optional in the scope but central in the pitch

**Importance:** Hackathon-story weakness; fixable.

**References:** Sections 1, 4, 5, 8, and 22.

The opening and architecture feature a challenger, while the implementation scope makes it optional. That is a reasonable scope cut, but the presentation must reflect what was actually built.

**Resolution:** Treat worker plus repair agent as the core collaboration. Include the challenger in the final pitch only if implemented and its selected cases add useful evidence. A random-sampling comparison is helpful if claiming challenger superiority; role separation alone does not establish it.

### 6. A frozen synthetic environment is not independent validation

**Importance:** Limitation on claims; already acknowledged.

**References:** Sections 7, 11, 20, and 21.

The same team authors the environment, outcome rules, and candidate vocabulary. Withheld combinations reduce leakage but may still favor the proposed repair mechanism. Committing a test does not make its task distribution externally representative.

**Resolution:** Label results as a synthetic proof of concept. Use an independently authored fixture or customer adapter for a later external check. Do not claim production readiness from the weekend experiment.

### 7. Recoverability needs an observation-aware oracle

**Importance:** Scoring specification blocker; fixable.

**References:** Sections 7 and 11.

The private ledger alone cannot decide whether the worker should complete or escalate. That depends on which public observations can become available within the allowed clock and action budget.

**Resolution:** For each recoverable fixture, verify a legal witness sequence that reaches supporting evidence within the budget. For unresolved fixtures, specify an observation schedule that remains inconclusive throughout the permitted horizon. Score the worker against its actual accessible evidence rather than demanding private knowledge.

## Minimum experiment before committing to the full build

1. Implement one resettable store fixture, explicit tool semantics, and a ledger-based scorer.
2. Define the same dispatcher, clock access, and budgets for all arms.
3. Run a competent worker and a handwritten reconciliation routine.
4. Generate one real candidate from a development failure.
5. Test the candidate on cases not used to write it and on clean controls.
6. Record genuine acceptance or rejection in Weave.

Only then spend substantial time on the dashboard, challenger optimization, or optional ARIA integration.

## What is already strong

The narrow failure story is understandable. A persistent, inspectable artifact can make improvement visible. The plan includes a real engineering baseline, separates authoritative state from the conversation, uses sponsor tooling for meaningful work, and acknowledges research prior art. These make the proposal worth testing, but they do not resolve the missing evidence.

## Decision

**Proceed with a bounded proof of concept after resolving the control, timing, and promotion contracts. Do not yet treat the idea as experimentally validated.**
