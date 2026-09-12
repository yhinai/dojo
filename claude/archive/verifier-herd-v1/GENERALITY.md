# The Generality Problem

**When is a patch general enough to publish to the shared pool?**

This is Herd's load-bearing question. Get it wrong in one direction and the pool fills with task-specific noise that breaks everyone. Wrong in the other and nothing propagates, the colony effect vanishes, and Herd degenerates into N independent hardening loops — which is just harden-v0 run in parallel.

---

## 1. Why the obvious answer fails

The published implementation asks the Fixer, in a prompt:

> *"Push to pool ONLY the changes that address a general attack class (e.g., timing, monkeypatching, permissions, general environment hardening). The changes must NOT contain any specifics of this task. When in doubt, do not make changes to the pool."*

That is a vibe check performed by the same agent that wrote the patch, on its own work, with no feedback signal. It fails three ways:

1. **No ground truth.** The Fixer has never seen another agent's verifier. It is guessing about a population it cannot observe.
2. **Self-assessment is exactly the thing this project exists to distrust.** Across 35 model-game cells, self-assigned scores all landed ≥0.70 while **15 of 35 scored below random** ([`2607.24300`](https://arxiv.org/abs/2607.24300)). We are not going to build a system whose central gate is an agent grading itself.
3. **"When in doubt, don't" is a silent kill switch.** Under uncertainty the Fixer defaults to not publishing, the pool stays empty, and the colony never forms. The failure is invisible — nothing breaks, nothing propagates.

## 2. The reframe

> **Generality is not a property of the patch text. It is an empirical property of the patch's behaviour on other agents' verifiers.**

So stop classifying and start **measuring**. This turns an unanswerable judgement call into an evaluation problem — which is the one kind of problem this whole project is already built to handle.

The shape it takes is a **clinical trial**: a candidate must demonstrate *efficacy* on hosts it was not designed for, and cause *no adverse events* on any of them, before it is licensed for the population.

That is also, conveniently, exactly what an immune system does. Nothing enters the shared repertoire on the strength of looking useful.

---

## 3. The pipeline

```
  local patch accepted by its own agent
            │
            ▼
   ┌────────────────────┐
   │  STAGE 0           │   active locally only; never auto-shared
   │  QUARANTINE        │
   └─────────┬──────────┘
             ▼
   ┌────────────────────┐   deterministic, ~50 LOC, kills most junk
   │  STAGE 1           │   reject if the diff references task-local vocabulary
   │  ADMISSIBILITY     │
   └─────────┬──────────┘
             ▼
   ┌────────────────────┐   cheap prior: what machinery does it touch?
   │  STAGE 1.5         │   order candidates; dedupe against the pool
   │  TRIAGE            │
   └─────────┬──────────┘
             ▼
   ┌────────────────────┐   apply to k OTHER agents' verifiers
   │  STAGE 2           │   measure efficacy + non-interference on each
   │  TRIAL             │
   └─────────┬──────────┘
             ▼
   ┌────────────────────┐   sequential e-process over trial outcomes
   │  STAGE 3           │   promote when E >= 1/alpha
   │  PROMOTION GATE    │
   └─────────┬──────────┘
             ▼
   ┌────────────────────┐   keep measuring; retract on adverse events
   │  STAGE 4           │   pool membership is revocable
   │  PHARMACOVIGILANCE │
   └────────────────────┘
```

---

## 4. Stage 1 — Admissibility (deterministic)

A patch is **inadmissible for the pool** if it references anything that only exists in its own task. This is a hard filter with no model in the loop, and it is fully explainable — you can point at the exact token that disqualified a patch.

```python
def task_vocabulary(task) -> set[str]:
    """Every content-bearing token that is specific to this task."""
    v = set()
    v |= identifiers(task.tests)           # test fn names, fixture names, class names
    v |= identifiers(task.reference_solution)
    v |= string_literals(task.tests)       # expected values, paths, magic constants
    v |= path_components(task.dir)         # task id, directory names
    v |= content_words(task.instruction)   # minus a stoplist
    return v - HARNESS_COMMON              # names shared by every task's scaffold

def admissible_for_pool(patch, task) -> tuple[bool, str | None]:
    tokens = identifiers(patch.added_lines) | string_literals(patch.added_lines)
    leak = tokens & task_vocabulary(task)
    if leak:
        return False, f"references task-local vocabulary: {sorted(leak)[:5]}"
    if any(f.startswith(task.dir) and f not in HARNESS_SHARED_FILES
           for f in patch.files_touched):
        return False, "modifies task-local files only"
    return True, None
```

**Why this is not merely a lint.** It encodes the actual definition of task-specificity: a patch that mentions `test_sort_descending` or the literal `42` from this task's expected output *cannot* be general, no matter how it is phrased. Roughly the majority of junk dies here, for free, before a single LLM call.

**Deliberate asymmetry:** admissibility is necessary, not sufficient. Passing Stage 1 earns a patch a *trial*, nothing more.

---

## 5. Stage 1.5 — Triage (cheap prior, saves trials)

Trials cost real LLM calls, so order candidates by expected information rather than trialing arbitrarily.

**Mechanism level** — what layer of machinery does the patch touch? This is a strong prior on generality and it is readable straight off the diff:

| Prior | Signal in the patch | Example |
|---|---|---|
| **High** | process / interpreter / OS machinery | subprocess isolation · import hooks · `sys.audit` hooks · env sanitization · file permissions · clock and timer capture · RNG seeding · capturing builtins before user code loads |
| **Medium** | harness-shared structure | test runner invocation · result parsing · artifact handling · resource limits |
| **Low** | assertion content | changing a specific expected value · adding a test for one behaviour · tightening one comparison |

This mirrors what the published colony actually converged on. Every layer in the final hardened verifier was mechanism-level: process isolation, monkeypatch capture, stack-introspection blocking, tensor-subclass detection, timing hardening, seed unpredictability. **Not one was assertion-level.** The prior is empirically grounded, not invented.

**Dedupe before trialing.** Embed the patch's *mechanism description* (not its diff text) and compare against pool members. Near-duplicates get merged into the existing entry as additional evidence rather than consuming a trial slot.

---

## 6. Stage 2 — The trial (the actual definition)

Apply the candidate patch to **k other agents' verifiers**, selected for maximum dissimilarity — different task family, different oracle type, different capability profile. Then on each host measure two things.

### Efficacy — does it block the attack *class* on a verifier it never saw?

This requires exploits to be **portable**, which means an exploit cannot be a literal payload. It has to be a *strategy that gets re-derived against the host*.

```
PortableExploit = (family, recipe)
    family : one of terminal-wrench's 11 categories
             hollow-implementation · output-spoofing · constraint-loophole ·
             structural-extraction · binary-hijacking · algorithmic-simplification ·
             mutable-input-tampering · keyword-gaming · metric-spoofing ·
             security-downgrading · deceptive-rationalization
    recipe : natural-language strategy, task-agnostic
```

To test efficacy on host H, the Red agent is told: *"Obtain a passing verdict from H's verifier using the {family} strategy."* It re-derives the attack against H's actual code.

> **This also repairs the circularity in the original proof moment.** Re-derivation is what makes transfer meaningful: you are testing whether the *defense class* holds, not whether one literal payload is blocked by the patch that was written to block it.

### Non-interference — does it break honest work it was not written for?

Run **each host's own Solver** against the patched verifier. Critically, use **≥2 diverse legitimate solutions per host**, not one reference implementation.

This guards against the exact bug the published work hit: because the KernelBench oracle solver never exercised `torch.cpp_extension.load_inline` or raw cuBLAS handles, **two over-restrictive defenses slipped past per-iteration validation** and had to be repaired by a separate post-loop pass. A single reference solution does not exercise enough of the surface to detect over-restriction.

### The definition

> A patch is **general** iff it is **efficacious on a significant fraction of hosts** and **harmless on all of them.**

Efficacy is the evidence signal; non-interference is a **hard veto**. One adverse event sinks the candidate — asymmetric on purpose, because a bad patch in the pool damages every agent at once, while a rejected good patch costs only one agent's local benefit.

---

## 7. Stage 3 — Promotion gate (sequential, not a threshold)

"It worked on 3 of 5 hosts" is a raw threshold, and raw thresholds against repeated trials are the same p-hacking problem the local loop already solved. Use the same machinery.

Each host trial is a **paired observation**: host H with the patch vs. host H without it, facing the same re-derived exploit.

```python
E = 1.0
for host in trial_hosts:                    # ordered by dissimilarity, most informative first
    blocked_with    = attack(host, patched=True,  family=f).blocked
    blocked_without = attack(host, patched=False, family=f).blocked

    if not non_interference(host, patched=True):
        return REJECT, "adverse event"      # hard veto, no accumulation

    if blocked_with == blocked_without:
        continue                            # tie: patch made no difference here, discard
    w = 1 if (blocked_with and not blocked_without) else 0
    E *= (1 + LAMBDA * (2*w - 1))

    if E >= 1 / ALPHA:
        return PROMOTE, f"E={E:.1f} after {host.n} hosts"
return QUARANTINE, "insufficient evidence"
```

Under `H0: Pr[w=1] <= 1/2` ("this patch is no better than nothing on a host it wasn't written for"), Ville's inequality bounds the false-promotion probability at α **under optional stopping** — so you may stop as soon as evidence crosses, and you can order hosts most-informative-first without invalidating the guarantee.

**The same gate now guards both the local loop and the pool.** One mechanism, two uses. That is worth saying out loud in the pitch — it is the kind of economy a builder panel notices.

---

## 8. Stage 4 — Pharmacovigilance (the pool can retract)

Promotion is a licence, not tenure. Every pool member carries earned counters:

```
PoolEntry:
    mechanism_summary : str
    capability_tags   : set[str]      # see §9
    hosts_tested      : int
    efficacy_count    : int
    adverse_count     : int
    promoted_at       : generation
    provenance        : (origin_agent, exploit_family, trial_record)
```

When a new agent joins the colony and pulls the pool, **its first run is also a fresh trial of every pool member.** If an entry causes a benign-pass regression on the newcomer, `adverse_count` increments; past a threshold the entry is **retracted** to quarantine and every agent drops it on next pull.

This is what prevents the two failure modes that would otherwise kill the colony:

- **Monoculture.** A defense that only appeared safe because the original cohort was homogeneous gets caught the moment a genuinely different agent joins.
- **Pool poisoning.** One bad "general" defense propagating everywhere is the single-point-of-failure in the whole design. Retraction bounds the blast radius to one generation. (Relevant: colluding agents poisoning shared memory via sub-threshold edits, [`2608.01637`](https://arxiv.org/abs/2608.01637).)

These counters are ACE-style helpful/harmful bookkeeping — except **earned by trial rather than asserted by a model.**

---

## 9. Generality is relative, not absolute

The sharpest correction to the naive framing:

> **Timing hardening generalizes across every task that measures time. It is meaningless for a task that doesn't.**

A patch is not general *in the abstract* — it is general **with respect to a capability set**. So the pool is **typed**, and hosts pull only what applies to them:

```
capability_tags ⊆ { timing, subprocess, filesystem, network, imports,
                    rng, permissions, resource_limits, introspection }
```

A patch inherits tags from the machinery it touches; an agent declares the capabilities its verifier exposes; a host pulls the intersection. Consequences:

- **Trials only run on hosts with the relevant capability.** No wasted trials, no spurious adverse events from a patch that was never applicable.
- **Reported transfer is honest.** "Efficacious on 4 of 5 *applicable* hosts" is a true claim; "4 of 5 hosts" would not be.
- **It gives you a second, sharper headline number:** *within-capability* transfer vs *cross-capability* transfer. The first will be strong. The second is the genuinely hard case and will be weaker — report both.

---

## 10. Failure modes, stated honestly

| Failure | Why it happens | Handled by |
|---|---|---|
| **Over-restriction** | Patch blocks the exploit *and* legitimate work, undetected because the local Solver's single reference solution never exercised that path | §6 non-interference with ≥2 diverse solutions per host, on each host's own solver |
| **Interaction effects** | Patch A and patch B are individually fine; together they break | Trial against the **current pool state**, not a clean baseline; composite smoke test before promotion |
| **Capability mismatch** | Timing defense trialed on a task with no timing surface | §9 typed pool |
| **Evidence starvation** | Too few hosts share a capability to accumulate evidence past `1/alpha` | Falls back to QUARANTINE — patch stays local, which is the correct conservative behaviour and is *visible* in the metrics rather than silent |
| **Monoculture** | Shared defenses converge; one novel attack defeats everyone | §8 retraction on newcomer trials; track defense-set diversity across agents as a monitored metric |
| **Pool poisoning** | A malicious or degenerate general patch propagates | Hard veto on adverse events + retraction + provenance on every entry |

---

## 11. What this buys the demo

A second readable comparison in exactly the shape of greedy-vs-gate — and this one is about the part of the system that is genuinely yours.

> **"We measured the pool's precision two ways."**
>
> Ask the Fixer whether its own patch is general — the published approach — and **X% of published patches later cause adverse events on other agents.**
> Make patches earn it by trial — **Y%.**

Plus a genuinely interesting artifact for the Q&A: **the pool itself, sorted by earned transfer count.** Judges can read it. Each entry says which agent discovered it, which exploit family produced it, how many hosts it was tried on, and how many it helped.

That is the difference between a shared lint config and an immune repertoire: **every antibody in it can tell you what infected somebody else, and prove it helped.**

---

## 12. Cost

| | |
|---|---|
| Stage 1 admissibility | deterministic, ~50 LOC, free |
| Stage 1.5 triage | one embedding per candidate, negligible |
| Stage 2 trial | the real cost — `k` hosts × (1 re-derived attack + ≥2 solver runs). Use cheap models here; this is precisely the "diverse cheap beats expensive identical" regime, and trials are embarrassingly parallel |
| Stage 3 gate | arithmetic |
| Stage 4 vigilance | rides along with each newcomer's first run, no extra cost |

Trials are the only meaningful spend, they parallelize perfectly, and admissibility kills most candidates before they reach that stage.

---

## 13. The one-line answer

> **A patch is general when it has blocked a re-derived attack on verifiers it never saw, harmed none of them, and accumulated enough evidence to pass the same sequential test we use everywhere else.**
>
> Not because a model said it looked general.
