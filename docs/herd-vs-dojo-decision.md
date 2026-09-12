> **Superseded direction:** This comparison concerns verifier-hardening HERD. The subsequent user-proposed design direction is shared-skill HERD; see [the active proposal](../claude/HERD.md). The reduced-scope recommendation below is historical and does not govern the new architecture.

# HERD versus DOJO — hackathon decision

## Recommendation

**Choose a reduced HERD for the hackathon. Keep DOJO as the lower-risk fallback.**

HERD has the stronger presentation hook and a more naturally interdependent agent team: a defense discovered on one task can be evaluated and reused on a different task. DOJO has a clearer initial customer and a smaller implementation surface, but its narrow refund-recovery example is particularly vulnerable to a competent handwritten routine solving the entire problem.

This is a judgment about hackathon fit, not a prize prediction or a finding that HERD works. Neither proposal currently supplies measured application results. The full HERD architecture is too broad for the initial build and contains blockers that must be corrected.

## Repository state reviewed

Ran `git pull --ff-only` on `main`; it returned `Already up to date`. Reviewed the repository at commit `365940c`, including `claude/HERD.md`, `claude/ARCHITECTURE.md`, `claude/GENERALITY.md`, `astra.md`, `astra-review.md`, and the older `ideas.md`.

The DOJO compared here is the refund-recovery proposal in `astra.md`, not the earlier general tool-learning proposal in `ideas.md`.

## Criteria comparison

| Criterion | Stronger choice | Reason |
|---|---|---|
| Three-minute hook | HERD | One task is exploited; a tested defense protects a different task. The sharing is easy to visualize. |
| Meaningful agent collaboration | HERD | Attacker, fixer, and legitimate-work verification have conflicting objectives and concrete artifacts. |
| Persistent improvement | Both, differently | DOJO improves a recovery routine. HERD improves verifier defenses; it must say that explicitly. |
| Initial production user | DOJO | Agent-support engineers have an understandable failure-to-fix workflow. HERD initially serves evaluation and benchmark maintainers. |
| Weekend implementation risk | DOJO | One synthetic store and bounded routine require less infrastructure than multi-host verifier hardening. |
| Weave and marimo integration | Tie | Both have substantial trace, evaluation, and interactive evidence workflows. |
| Novelty | Neither established | DOJO overlaps existing agent optimization; HERD's attack/fix/solve loop and shared defense pool already exist in harden-v0. |
| Best distinctive contribution to build | HERD | Evidence-based admission of shared defenses, including explicit rejection when a fix breaks legitimate work on another host. |

Do not justify this recommendation using unverified judge preferences, blanket statistics about all agents, or assumed absence of competing hackathon projects.

## Findings that prevent accepting HERD as written

### 1. The shared-pool gate cannot promote with its stated defaults

`claude/ARCHITECTURE.md` section 2.5 selects five hosts, initializes E to 1, uses lambda = 0.5, and requires E >= 1 / 0.05 = 20. Each winning discordant observation multiplies E by 1.5.

Even five consecutive wins produce only **1.5^5 = 7.59375**. At least **eight consecutive wins** are needed to cross 20; losses require additional evidence and ties add none. The shown routine resets E on the next trial invocation, so repeated five-host invocations do not solve this.

This is not merely a tunable optimization. As written, the colony's headline behavior—admission followed by propagation—cannot occur through that gate.

**Correction:** either implement a valid sequential design with a sufficient budget and persistent evidence for an unchanged candidate/comparator/protocol, or use a clearly labeled finite-suite engineering acceptance rule for the MVP. Do not silently relax alpha to produce an attractive demonstration. Replaying the same deterministic hosts does not create independent new evidence.

### 2. A per-candidate statistical guarantee is not a colony-wide guarantee

The PACE paper explicitly describes a per-decision guarantee, not a run-level guarantee. Its validity also depends on the conditional null and valid paired observations. Selecting promising hosts adaptively or repeatedly reusing outcomes does not become valid merely because the update formula is an e-process.

**Correction:** document the sampling assumptions and scope of any claimed bound. If claiming control across many candidates, use an appropriate multiplicity policy. Do not promise approximately zero false promotions in HERD based on a result from different experiments.

Source: [PACE](https://arxiv.org/html/2606.08106v1).

### 3. The main mechanism already exists

The original harden-v0 repository implements Hacker, Fixer, Solver, and a shared defense pool. Therefore HERD's claim that no mechanism lets one team's discovery protect others is contradicted by its own implementation foundation.

**Correction:** credit the existing loop and pool. Define the contribution as measured cross-host admission and regression checking, plus useful evidence presentation. Whether that contribution is novel beyond this baseline still requires broader comparison.

Source: [harden-v0](https://github.com/few-sh/harden-v0).

### 4. Credential labels do not enforce the proposed trust boundary

The architecture serves a pool using `git daemon --enable=receive-pack` while describing `POOL_PUSH_KEY` as the protection against unauthorized writers. The unauthenticated git transport does not enforce that key. Merely telling agents to clone read-only is not access control.

Also, a hash chain written after ingesting an agent-controlled trajectory preserves that submitted data; it does not establish that the reported commands actually executed. Separate processes alone do not establish filesystem or credential isolation.

**Correction:** make the pool non-writable from attack sandboxes, have the trusted runner perform local commits, and expose a read-only export. Capture authoritative execution events through the runner outside the sandbox. State exactly what a hash chain does and does not prove.

### 5. The held-out family boundary is inconsistent

The exploit registry permits the Trial Runner to consume any family, while the proposal claims some families are never used in hardening. The live newcomer procedure can also retract pool entries based on the held-out result.

**Correction:** split admission-validation families from final audit families. Final audit runs must be read-only with respect to the pool and selection process. Any later retraction based on audit results starts a new development cycle; it cannot retroactively preserve the original untouched-test claim.

### 6. Paired attack evaluation needs a defined protocol

The design calls separately generated attacks against patched and unpatched hosts a paired comparison. Separate adaptive attempts may produce different payloads, and failure to discover an exploit is not proof that none exists.

**Correction:** distinguish two experiments: replay a host-specific fixed payload on both variants to measure patch effect; then run equally budgeted adaptive attacks against each variant to measure robustness against that attacker. Record seeds, budgets, errors, and the outcome definition. Neither experiment establishes immunity to every exploit.

### 7. The slider cannot reconstruct an alternate colony history

Changing alpha can change which patches exist, which later attacks are attempted, and which candidate patches are proposed. Stored outcomes from one policy do not reveal every counterfactual outcome under another policy.

**Correction:** label the slider as a fixed-candidate decision replay. Show only decisions supported by stored paired evaluations. A counterfactual immunity curve requires executing and evaluating the alternative configurations or clearly labeling it as a model-based estimate.

### 8. The architecture checker is not implementation verification

`python3 claude/verify_architecture.py` passes, but it checks a manually declared graph of components and artifact labels. It does not execute isolation, validate sequential-test assumptions, verify pool permissions, or demonstrate defense transfer. Its pass coexists with the five-host arithmetic blocker.

**Correction:** call it a structural consistency check and add actual behavioral tests as the system is implemented.

## The reduced HERD to build

**Product sentence:** HERD tests whether a defense discovered for one agent's evaluator can help other evaluators without rejecting legitimate work.

### Core scope

- Three small Python tasks with different verifier programs and one compatible shared harness boundary.
- One documented exploit family to start, with task-specific payloads.
- One attacker, one fixer, and a deterministic runner checking legitimate solutions.
- A versioned candidate defense, applied through a defined shared wrapper/configuration interface. Avoid assuming a raw diff applies to arbitrary unrelated programs.
- A local candidate store, a quarantined state, and a trusted promotion action.
- Two or more diverse legitimate solutions per host; this is coverage, not a proof of harmlessness.
- Weave traces and candidate evidence.
- One marimo page showing the original exploit, proposed defense, cross-host tests, and rejection/acceptance.

### MVP acceptance rule

For this small demo, a fixed finite-suite rule is acceptable if described honestly: the known exploit is blocked, predeclared cross-host attack cases improve, all registered legitimate controls still pass, and the candidate stays within the allowed modification scope. Report raw outcomes. Make no 95% generality or universal immunity claim.

A properly implemented sequential gate can follow when there are enough fresh, valid observations. It need not be the first demonstration.

### Required comparison

Compare unchanged verifiers, a basic handwritten shared defense, and the agent-generated defense with the same fixtures. If claiming improved pool admission, also compare blind/local-only sharing against cross-host validation on a frozen candidate set. Measure both blocked attacks and rejected legitimate solutions.

### Demo

1. An incorrect solution passes task A's weak verifier.
2. The fixer proposes a concrete shared defense.
3. A candidate that also blocks legitimate work on task B is rejected.
4. A candidate that passes the registered checks is admitted.
5. Apply it to task C, which was excluded from proposal and admission. Run the fixed attack and legitimate controls. Show the actual result, without promising success beforehand.

The core transfer claim is across tasks. Transfer across entirely withheld exploit families is an additional experiment, not a prerequisite for the first useful proof of concept.

### Cut initially

Eight-agent colonies, ten generations, learned action probes, multi-model monitor ensembles, cross-domain generality, production attestation, counterfactual immunity charts, and ARIA automation. ARIA can be added after a real analysis workflow is available.

The official harden-v0 README currently lists Python 3.12+, Harbor, and a Linux Docker Engine requirement for its pool mode. Do not assume the pooled path works unchanged on this macOS workstation. Use a verified Linux environment or the small local runner described above; report reused infrastructure accurately.

## Stop condition and fallback

Before building the control room, demonstrate one valid cross-host transfer while preserving registered honest solutions. If that cannot be reproduced in a short initial spike, choose DOJO's smaller recovery experiment. This condition reflects implementation risk, not reluctance to choose.

**Final choice: reduced HERD for hackathon impact; DOJO for lower build risk and the clearer initial customer workflow. Neither is production-ready today.**
