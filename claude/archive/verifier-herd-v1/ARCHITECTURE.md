# Herd — System Architecture

Companion to [HERD.md](HERD.md) (the idea) and [GENERALITY.md](GENERALITY.md) (the pool-admission mechanism). This document is the build spec: components, data model, control flow, trust boundaries, integrations, and a verification section at the end. A structural checker lives at [`verify_architecture.py`](verify_architecture.py).

---

## 0. Design invariants

Everything below serves five invariants. If a change violates one, the change is wrong.

| # | Invariant | Why |
|---|---|---|
| **I1** | **The audited process cannot write the audit record.** Agents hold no credential to the audit Weave project or the ledger. | Weave is observability, not an attested log; a trace of a lie is a faithful record of a lie. METR: >20% of agents attempted transcript tampering. |
| **I2** | **The only path into the shared pool is through the trial gate.** Fixers write to quarantine, never to the pool. | Generality is earned by trial, not declared ([GENERALITY.md](GENERALITY.md)). |
| **I3** | **Every promotion — local or pool — passes the same sequential test.** No "keep it if the score went up." | Greedy acceptance commits 30–42% false edits (PACE). |
| **I4** | **Detectors key on the action surface, not narration.** A detector must not lose more than a small tolerance when reasoning text is stripped. | Frontier judge TPR@5%FPR falls 0.82 → 0.44 without narration (Terminal Wrench). |
| **I5** | **Every number shown has a held-out source, an *n*, and an interval.** | A DeepMind judge is in the room. |

---

## 1. System overview

```
┌──────────────────────────── UNTRUSTED DOMAIN ─────────────────────────────┐
│  credentials: INFERENCE_KEY, WANDB_KEY[herd-agents]                       │
│                                                                           │
│   ┌───── Agent Cell 1 ─────┐   ┌───── Agent Cell 2 ─────┐     ...  ×N     │
│   │ Red → Fixer → Solver   │   │ Red → Fixer → Solver   │                 │
│   │      ↓ local gate      │   │      ↓ local gate      │                 │
│   │   [quarantine]         │   │   [quarantine]         │                 │
│   └──────┬─────────▲───────┘   └──────┬─────────▲───────┘                 │
│          │ traj    │ pool pull        │ traj    │ pool pull               │
│          ▼         │ (read-only)      ▼         │                         │
│   ┌──────────────────────── Sandboxes (Docker, per attempt) ────────────┐ │
│   └─────────────────────────────────────────────────────────────────────┘ │
└──────────┬──────────────────────────────────┬────────────────────────────┘
           │ trajectories (FS, ATIF JSON)     │ quarantine candidates
           ▼                                  ▼
┌──────────────────────────── TRUSTED DOMAIN ───────────────────────────────┐
│  credentials: WANDB_KEY[herd-audit], LEDGER_SIGNING_KEY, POOL_PUSH_KEY    │
│                                                                           │
│   ┌────────────┐    ┌──────────────┐    ┌──────────────┐                  │
│   │  Auditor   │    │ Trial Runner │    │ Orchestrator │                  │
│   │ detectors  │    │ admissibility│    │ generations  │                  │
│   │ verdicts   │    │ triage       │    │ barrier      │                  │
│   │ ledger     │    │ trial + gate │    │ scheduling   │                  │
│   └─────┬──────┘    └──────┬───────┘    └──────────────┘                  │
│         │                  │ promote                                      │
│         ▼                  ▼                                              │
│   ┌────────────┐    ┌──────────────┐                                      │
│   │  Ledger    │    │    Pool      │◀── vigilance (retract)               │
│   │ hash-chain │    │  git, typed  │                                      │
│   └────────────┘    └──────────────┘                                      │
└──────────┬────────────────────────────────────────────────────────────────┘
           │ Weave [herd-audit] · metrics
           ▼
┌───────────────────────── OBSERVATION DOMAIN (read-only) ──────────────────┐
│   Weave UI · marimo Control Room · W&B Automation → ARIA                  │
└───────────────────────────────────────────────────────────────────────────┘
```

Three domains. Data flows down; credentials never flow up.

---

## 2. Components

### 2.1 Task Registry

| | |
|---|---|
| **Owns** | tasks, their verifiers, capability tags, ≥2 legitimate reference solutions each |
| **Source** | terminal-wrench `tasks/<id>/<model>/original_task/` (331 tasks); optionally ControlArena settings (`apps`, `bash`, `bigcodebench`) |
| **Produces** | `Task` records |
| **Consumed by** | Agent Cells, Trial Runner (host selection) |

Capability tags are declared per verifier from what it exposes: `{timing, subprocess, filesystem, network, imports, rng, permissions, resource_limits, introspection}`. **Two** reference solutions minimum — one exercises the primary path, one deliberately exercises an alternate API path — to catch over-restrictive patches (§GENERALITY 6).

### 2.2 Exploit Library

| | |
|---|---|
| **Owns** | portable exploits `(family, recipe)` |
| **Source** | terminal-wrench's 3,632 hack trajectories, clustered by `observed_categories` into the 11 families; recipes distilled per family |
| **Split** | families **A–D** → training (seen by the colony); families **E, F** → held out, never used for hardening; additionally a held-out *task* split |
| **Produces** | `PortableExploit` records |
| **Consumed by** | Red agents (training families only), Trial Runner (any family, re-derived), Metrics (held-out families) |

⚠️ Apply the leak filter from `docs/implementation.md §6` before using any `sanitized` trajectory as training signal — 34.3% still leak role-assignment language, and raw `hack_trajectories/` leak the red-team prompt outright.

### 2.3 Agent Cell (×N)

One task, one verifier, three roles, one local gate. Runs in the untrusted domain.

| Role | Input | Output | Model tier |
|---|---|---|---|
| **Red** | task + verifier + a training family recipe + feedback from own prior failed attempts | attempt trajectory + verdict (`passed_without_solving` / `blocked` / `solved_legitimately`) | cheap (W&B Inference) |
| **Fixer** | task + verifier source + Red's successful trajectory summary + current pool state | candidate patch (git diff on `tests/` and/or `environment/`) | mid |
| **Solver** | task + patched verifier + reference solutions | pass/fail per reference solution | cheap |
| **Local gate** | paired outcomes (incumbent vs. candidate) across the task's dev instances | `ACCEPT` → quarantine · `REJECT` | arithmetic |
| **Replay** | the specific Red trajectory that produced the patch | `still_lands` / `blocked` — if it still lands, reject even though Solver passed | cheap |

Cell state machine per generation:

```
        ┌──────────┐  Red fails all R  ┌────────┐
   ─────▶  ATTACK   ├──────────────────▶ ROBUST │ (this generation)
        └────┬─────┘                   └────────┘
             │ Red succeeds
             ▼
        ┌──────────┐  legitimate ×3   ┌────────┐
        │   PATCH  ├──────────────────▶ ROBUST │
        └────┬─────┘                  └────────┘
             │ candidate
             ▼
        ┌──────────┐  Solver fails    ┌──────────────┐
        │ VALIDATE ├──────────────────▶ REUSE_HACK   │──▶ PATCH (next gen)
        └────┬─────┘                  └──────────────┘
             │ Solver passes
             ▼
        ┌──────────┐  replay lands    ┌──────────────┐
        │  REPLAY  ├──────────────────▶ REJECT_PATCH │──▶ PATCH (next gen)
        └────┬─────┘                  └──────────────┘
             │ blocked
             ▼
        ┌──────────┐  E < 1/α          ┌──────────────┐
        │  GATE    ├──────────────────▶ REJECT_PATCH │
        └────┬─────┘                  └──────────────┘
             │ E ≥ 1/α
             ▼
        ┌────────────┐
        │ QUARANTINE │──▶ Trial Runner picks up
        └────────────┘
```

Hyperparameters (from the published loop): `R=3` Red retries, `K=10` max generations, verifier-aware Red for the first `B=8` then blind, robust after 3 consecutive "legitimate" verdicts, `α=0.05`, `λ=0.5`.

### 2.4 Sandbox

Docker container per attempt. Provided by ControlArena / Harbor. The verifier runs **after** the agent finishes, in the same container image but the agent's process has exited. Mounts:

| Mount | Mode | Visible to |
|---|---|---|
| `/app` (task workspace) | rw | Red, Solver |
| `/eval_env/` (verifier source) | ro | Red, only while verifier-aware |
| `/previous_hacks/` | ro | Red |
| `/pool/` | ro | Fixer |
| `/logs/artifacts/` (git repo) | rw | Fixer only |

No network egress except the inference endpoint. No `WANDB_KEY[herd-audit]`, no `POOL_PUSH_KEY`, no `LEDGER_SIGNING_KEY` in the environment. (I1)

### 2.5 Trial Runner

Runs in the trusted domain. Implements [GENERALITY.md](GENERALITY.md) §3–8.

```
loop over quarantine (ordered by triage prior):
    candidate ← next
    if not admissible(candidate):            REJECT_POOL (keep local); continue
    hosts ← select_k_dissimilar(candidate.capability_tags, k=5)
    E ← 1
    for host in hosts:
        if not non_interference(host, candidate):   REJECT_POOL "adverse"; break
        w ← paired_efficacy(host, candidate, re-derive=True)
        if w is TIE: continue
        E ← E·(1 + λ(2w−1))
        if E ≥ 1/α:  PROMOTE(candidate); break
    else: QUARANTINE (insufficient evidence; re-eligible next generation)
```

Trial execution (Red re-derivation, Solver runs) happens **in sandboxes** — untrusted execution. Trial *orchestration and the gate decision* happen here — trusted. The Trial Runner holds `POOL_PUSH_KEY`; it is the **only** component that does. (I2)

### 2.6 Pool

| | |
|---|---|
| **Storage** | bare git repo, served by `git daemon --enable=receive-pack`, bound to the Docker bridge; agents clone read-only |
| **Entry** | `PoolEntry` (§3) — patch + mechanism summary + capability tags + earned counters + provenance |
| **Writers** | Trial Runner only (promotion, retraction) |
| **Readers** | every Agent Cell's Fixer, each generation, filtered by capability intersection |
| **Sync** | lockstep — Orchestrator barrier ensures every cell sees the same pool SHA at a generation boundary; a cell that pulled new commits runs a *pool-sync* iteration (Fixer integrates, no attack) which does not count toward `K`; anti-stall cap `S=1` |

Retraction: on a newcomer's join or any trial, an entry whose `adverse_count` crosses threshold is moved to `retracted/` with reason; all cells drop it on next pull.

### 2.7 Detector Ensemble

Each detector is a Weave `Scorer`. Two classes, deliberately:

| Class | Detector | Signal | Catches |
|---|---|---|---|
| **Signature** | `verifier_tamper` | diff of `tests/`, `conftest.py`, `sitecustomize.py`, `pyproject.toml` disable codes, `# type: ignore`, `#checkov:skip=`, shadowed stdlib modules | enumerated tampering patterns |
| **Signature** | `replay_diff` | re-execute a sample of claimed tool calls in a shadow sandbox; diff actual vs. claimed output | spoofed tool output |
| **Behavioural** | `frozen_regression` | re-run a frozen suite of old tasks after every promotion | capability erosion, *regardless of mechanism* |
| **Behavioural** | `noise_floor` | is the claimed gain inside run-to-run variance (paired, k repeats) | laundered noise |
| **Learned** | `action_probe` | embedding of the **stripped** trajectory (tool calls + observations only) → logistic regression, trained on terminal-wrench with the leak filter applied | action-surface anomalies |
| **Ensemble** | `cheap_ensemble` | 3 diverse cheap monitors (different prompts, 1–10 integer scale), arithmetic mean; select by prune-bottom-quartile-then-diversify | broad first pass |
| **Escalation** | `strong_monitor` | invoked only when `cheap_ensemble` score is in the ambiguous band | budget-efficient depth |

**The promotion gate consumes only the behavioural pair.** Signature and learned detectors *explain* a catch to a human; they do not decide promotions. This is the answer to *"would it catch an exploit you didn't think of?"*

**I4 check, enforced in CI:** every detector is evaluated on the held-out set twice — full trajectory and stripped — and the stripped-minus-full TPR@5%FPR delta is reported. A detector whose delta exceeds tolerance is flagged as narration-dependent.

### 2.8 Auditor

Trusted. Holds `WANDB_KEY[herd-audit]` and `LEDGER_SIGNING_KEY`.

1. Ingests trajectories from the untrusted FS drop (ATIF-v1.6 JSON — the terminal-wrench / Terminus-2 format)
2. Runs the Detector Ensemble → per-trajectory verdicts + scores
3. Logs each trajectory and its verdict to Weave project `herd-audit` as a call with attached scorer feedback
4. Appends an `EvidenceBundle` to the Ledger

Agents also write their own rich traces (via `@weave.op`) to a **separate** project `herd-agents` with a **separate** key. Those traces feed the propagation graph and the demo. They are *observability*, not evidence. Verdicts live only in `herd-audit`. (I1)

### 2.9 Ledger

Append-only JSONL. Each entry carries `prev_hash` and `hash = sha256(prev_hash ‖ canonical_json(entry))`. Written only by the Auditor and Trial Runner (both trusted). Anyone can verify the chain offline with ~10 lines. This is the tamper-evidence Weave does not provide.

### 2.10 Metrics

Computed from Ledger + Weave `herd-audit`, never from agent self-reports.

| Metric | Formula | Held-out on |
|---|---|---|
| `colony_asr[g]` | mean over cells of (Red successes / Red attempts) at generation `g` | training families |
| `herd_immunity[g]` | ASR on cells that **never** received the attack whose patch now protects them | training families, non-origin cells |
| `transfer_task` | ASR on held-out **tasks**, pool vs. no-pool | held-out tasks |
| `transfer_family` | ASR on held-out **families E, F**, pool vs. no-pool | held-out families — the hard number |
| `benign_pass[g]` | Solver pass rate on reference solutions, all cells | all |
| `detector_tpr_5fpr` | per detector, full and stripped | held-out labeled trajectories |
| `false_commit` | promoted patches later retracted or failing audit | — |
| `pool_precision` | 1 − (entries with adverse events / entries promoted) | — |
| `exploit_novelty[g]` | fraction of Red successes not matching any pool entry's family+mechanism | — |

All rates reported with binomial CI and `n`; before/after comparisons use a paired test. (I5)

### 2.11 Orchestrator

Runs generations. Within a generation: all cells in parallel (bounded by a sandbox semaphore); barrier; Trial Runner processes quarantine (trials parallel across candidates and hosts); pool sync; Auditor pass; Metrics; next generation. Persists a `GenerationRecord` so a crash resumes, not restarts.

### 2.12 Control Room (marimo)

Read-only. Polls Weave `herd-audit` via REST (`/calls/stream_query`, `/calls/stats`) and the Ledger file on `mo.ui.refresh(default_interval="2s")`. One reactive control: a slider on `α` that recomputes, from stored paired outcomes, which promotions would have survived — and redraws the immunity curve. Panels: colony ASR bars per cell · propagation graph (origin cell → recipients per pool entry) · pool table sorted by earned transfer · two-pane trajectory viewer (narration | commands) · detector full-vs-stripped bars · greedy-vs-gate comparison.

### 2.13 ARIA

W&B Automation: event *"A Weave metric crosses a threshold"* on `herd-audit` (e.g. `herd_immunity` drops, or `pool_precision` drops) → action *"Trigger ARIA"* with a templated prompt: *"Immunity dropped at generation ${g}. Read the ledger entries and traces for that generation, identify which pool entry or which cell is responsible, and write an incident report."* This is ARIA's only programmatic hook. Requires Smart features on a team project — **verify on site.**

---

## 3. Data model

```python
Task:
    task_id: str
    source: "terminal-wrench" | "control-arena:<setting>"
    instruction: str
    verifier_dir: path                 # tests/ + environment/
    capability_tags: set[str]
    reference_solutions: list[path]    # len >= 2
    split: "train" | "heldout_task"

PortableExploit:
    family: str                        # one of the 11 terminal-wrench categories
    recipe: str                        # task-agnostic strategy text
    split: "train" | "heldout_family"
    provenance: list[trajectory_id]

Trajectory:                            # ATIF-v1.6 (Terminus-2), as in terminal-wrench
    schema_version: "ATIF-v1.6"
    session_id: str
    agent: {name, version, model_name, extra}
    steps: list[Step]                  # {step_id, source, message, tool_calls[], observation, metrics}
    final_metrics: {...}
    # Herd adds a sidecar:
    herd: {cell_id, role, generation, family, verifier_sha, attempt_index}

Patch:
    patch_id: str
    cell_id: str
    generation: int
    diff: str
    files_touched: list[str]
    mechanism_summary: str             # LLM one-liner, used for dedupe embedding only
    capability_tags: set[str]          # inferred from files/APIs touched
    origin_exploit: PortableExploit
    local_gate: {E_final, n_pairs, decision}
    replay: {still_lands: bool}
    status: "quarantine" | "pool" | "rejected_pool" | "retracted"

TrialRecord:
    patch_id: str
    hosts: list[{task_id, w: 0|1|"tie", non_interference: bool, attack_trajectory_id}]
    E_trace: list[float]
    decision: "PROMOTE" | "REJECT_ADVERSE" | "QUARANTINE"
    alpha: float; lam: float

PoolEntry:
    patch_id: str
    mechanism_summary: str
    capability_tags: set[str]
    hosts_tested: int
    efficacy_count: int
    adverse_count: int
    promoted_at: int                   # generation
    provenance: {origin_cell, family, trial_record_id}
    status: "active" | "retracted"

EvidenceBundle:                        # one Ledger entry
    seq: int
    prev_hash: str
    kind: "verdict" | "promotion" | "retraction" | "generation"
    payload: {...}                     # trajectory_id + scores, or patch_id + trial_record, ...
    hash: str                          # sha256(prev_hash || canonical_json(payload))

GenerationRecord:
    g: int
    pool_sha: str
    cells: dict[cell_id, CellState]
    metrics: dict[str, {value, n, ci}]
```

---

## 4. Control flow

### 4.1 One generation

```
1. Orchestrator: barrier — all cells at pool SHA s_g
2. Cells (parallel):
     if pool has new commits since s_{g-1}:  POOL_SYNC (Fixer integrates; no attack; not counted)
     else: ATTACK → PATCH → VALIDATE → REPLAY → GATE  (per §2.3 state machine)
3. Barrier
4. Trial Runner: drain quarantine → PROMOTE / REJECT / hold
5. Pool: apply promotions and retractions → s_{g+1}
6. Auditor: ingest all trajectories from g → detectors → Weave[herd-audit] → Ledger
7. Metrics: compute → Weave leaderboard → Ledger "generation" entry
8. Automation: threshold checks → ARIA if triggered
9. g ← g+1
```

### 4.2 Trial of one candidate

```
admissible?                     no → REJECT_POOL(reason) → Ledger
triage prior; dedupe vs pool    duplicate → merge evidence into existing entry
hosts ← k most dissimilar cells sharing ≥1 capability tag
for host in hosts:
    apply patch to host verifier in a fresh sandbox
    Solver(host, ref_sol_1), Solver(host, ref_sol_2)    both must pass → else REJECT_ADVERSE
    Red(host, family=candidate.origin_exploit.family, re-derive)   with patch → b_with
    Red(host, same)                                                without   → b_without
    w ← 1 if (b_with blocked ∧ b_without not) else 0 if reverse else TIE
    update E; check 1/α
record TrialRecord → Ledger
```

### 4.3 Newcomer join (also the live demo)

```
cell_new ← Task from heldout_task split, verifier never in the colony
show verifier code beside an existing cell's verifier      (visibly different)
Red(cell_new, family ∈ heldout_family, re-derive)   no pool  → expect: breached
cell_new pulls pool (capability intersection)
Red(cell_new, same family, re-derive)               with pool → expect: blocked
Solver(cell_new, ref_sol_1..2)                                → must pass
every pool entry applied counts as a vigilance trial: adverse → retract
```

### 4.4 Audit of one trajectory

```
strip → actions-only view
run signature, behavioural, learned, ensemble detectors on BOTH views
escalate to strong monitor iff ensemble score in ambiguous band
verdict + per-detector scores → Weave[herd-audit] call.feedback / apply_scorer
EvidenceBundle(kind="verdict") → Ledger
```

---

## 5. Trust boundaries — credential matrix

| Credential | Colony runner / cells | Sandboxes | Trial Runner | Auditor | Control Room | ARIA |
|---|---|---|---|---|---|---|
| `INFERENCE_KEY` | ✔ | ✔ | ✔ (trial execution) | ✔ (monitors) | — | — |
| `WANDB_KEY[herd-agents]` | ✔ | — | — | — | read | — |
| `WANDB_KEY[herd-audit]` | **—** | **—** | ✔ | ✔ | read | read (W&B-side) |
| `POOL_PUSH_KEY` | **—** | **—** | ✔ | — | — | — |
| `LEDGER_SIGNING_KEY` | **—** | **—** | ✔ | ✔ | — | — |

Process isolation: colony runner, Trial Runner, and Auditor are **separate OS processes** with separate environments. Sandboxes are containers. The Control Room has no write credential of any kind.

---

## 6. Integrations — exact surfaces used

| Sponsor / tool | Surface | Used for |
|---|---|---|
| **Weave** | `weave.init(project)` ×2 (two projects, two keys) · `@weave.op()` on every role call · `weave.Scorer` subclasses for every detector · `call.apply_scorer()` at audit time · `client.get_calls(filter=..., scored_by=[...], include_feedback=True)` for the propagation graph · `weave.Evaluation` + `Leaderboard` for generations · `EvaluationLogger` linking trials to eval rows · Agents view (`start_conversation/turn/llm/tool`) for role-structured traces | nervous system |
| **W&B Inference** | OpenAI-compatible `https://api.inference.wandb.ai/v1`, `project=` header; cheap models (GPT-OSS-20B class) for Red/Solver/cheap monitors; call `GET /v1/models` at hack time | colony scale |
| **marimo** | `mo.ui.refresh` polling · `mo.ui.slider` on α · `mo.ui.table` for the pool · `marimo run control_room.py` | control room |
| **ARIA** | W&B Automation, event *Weave metric crosses threshold* → action *Trigger ARIA*, templated prompt | epidemiologist |
| **ControlArena** | `pip install control-arena`; settings `apps`/`bash`/`bigcodebench`; `attack_policy_builder` / `honest_policy_builder`; `basic_monitor_builder`; `compute_safety` / `compute_usefulness`; `control-arena trajectory export` | optional second task source + the safety/usefulness metric pair |
| **harden-v0** | `harden/loop.py` state machine, `harden/pool.py` git daemon + `PoolCursor`, `harden/instructions.py` role prompts, `_run_targeted_replay` | the per-cell loop and pool transport — reused, not rewritten |
| **terminal-wrench** | `index/trajectories.json`, `tasks/*/original_task`, `prompts/{hack_prompt_v5.md, sanitize_prompt.txt, monitor_judge_v1.txt}`, the 11 categories | tasks, exploits, labeled detector data, baseline judge |

---

## 7. Concurrency and failure

| Concern | Handling |
|---|---|
| Sandbox limit | semaphore; cells and trials share the pool of containers |
| Generation barrier | `asyncio` barrier as in harden-v0; a cell that crashes is marked `SKIPPED` for that generation, not blocking |
| Trial host unavailable | skip host, do not count as tie or evidence |
| Pool push conflict | Trial Runner is the sole writer, so none by construction; still `pull --rebase` before push |
| Weave outage | Auditor buffers to Ledger first (Ledger is the source of truth), replays to Weave on recovery |
| Attempt timeout | recorded as `timeout`, not `blocked`; excluded from ASR denominators |
| Crash mid-generation | `GenerationRecord` checkpoint; resume at step, not from `g=0` |
| Long run | launch the colony run early; generations are independent checkpoints so a partial run still produces every metric up to `g` |

---

## 8. What the demo reads from

| Beat | Artifact |
|---|---|
| 0:00 two-pane trajectory | any `Trajectory` with a `verifier_tamper` hit: `steps[i].message` (left) vs `steps[i].tool_calls` (right) |
| 0:12 colony under attack | `colony_asr[0]` per cell |
| 0:27 propagation footage | Weave `herd-agents` traces + `PoolEntry.provenance` → origin cell → recipient cells |
| 0:47 live cross-verifier | §4.3 newcomer join, run live |
| 1:22 the numbers | `transfer_task`, `transfer_family` with CI and n |
| 1:37 why believe it | `detector_tpr_5fpr` full vs stripped · greedy-vs-gate replay from stored paired outcomes |
| 2:07 cost | `benign_pass[0]` vs `benign_pass[g]` · defense-set diversity across cells |
| 2:22 sponsors | control room slider on α; ARIA incident report from the Automation |

---

## 9. Verification

### 9.1 Against verified tool facts

Each architectural assumption below was checked against the documentation and papers in `docs/` during research. Status ✔ = confirmed, ⚠ = confirmed with a caveat the architecture already handles, ✖ = would have been wrong.

| Assumption in this document | Evidence | Status |
|---|---|---|
| Weave traces can be read back at runtime (`get_calls`, `scored_by`, `include_feedback`) | Weave docs, querying-calls | ✔ |
| `call.apply_scorer()` applies a scorer to a live/production call | Weave scorers docs | ✔ |
| Leaderboards are creatable programmatically (Python) | Weave leaderboards docs | ✔ |
| Weave has an Agents view with conversation/turn/llm/tool spans | custom-agents quickstart (GA June 2026) | ✔ |
| **Weave is tamper-evident** | Weave is observability; no hash chain, no attestation; agent with the key can write | ✖ → architecture adds Ledger + two projects + credential split (I1) |
| ARIA has a programmatic API | No — chat UI only; the sole hook is Automation → Trigger ARIA | ⚠ → §2.13 uses exactly that hook; on-site verification required |
| marimo can poll and re-render on an interval without a background thread | `mo.ui.refresh` reruns downstream cells | ✔ |
| harden-v0 ships a git-served shared pool with lockstep barrier | `harden/pool.py` `PoolServer`/`PoolCursor`, `asyncio` barrier, anti-stall `S=1` | ✔ |
| harden-v0 has a targeted-replay gate that rejects a fix even if Solver passes | `_run_targeted_replay`, `_TARGETED_REPLAY_SUFFIX` | ✔ |
| terminal-wrench trajectories are ATIF-v1.6 / Terminus-2 JSON with `steps[].tool_calls` and `observation` | verified against `tasks/1012/.../trajectory.json` | ✔ |
| terminal-wrench has 11 labeled categories, multi-label | README + `observed_categories` field | ✔ |
| terminal-wrench is loadable from HuggingFace | **No confirmed release**; `build_hf_release.py` only stages | ⚠ → §2.1/2.2 clone the repo |
| Raw `hack_trajectories/` are safe to train on | No — red-team prompt leaks; BoW on first two actions gets AUC ≈ 0.97; 34.3% of `sanitized` still leak | ⚠ → §2.2 applies the leak filter |
| A frontier judge degrades when narration is stripped | TPR@5%FPR 0.8235 → 0.4400 | ✔ (motivates I4) |
| Greedy acceptance is unsafe | PACE: 30–42% false commits with a real gain; 72–100% without | ✔ (motivates I3) |
| The e-process gate is valid under optional stopping | Ville's inequality on the wealth supermartingale | ✔ |
| ControlArena is pip-installable with attack/honest policies and safety/usefulness metrics | `pip install control-arena`; README quickstart | ✔ (Python ≥3.11, Docker, two providers) |
| Diverse cheap monitors beat identical ones; naive diversity selection backfires | pAUC 0.8160 vs 0.7621; diversity-only 0.717 < random 0.769 | ✔ → §2.7 prune-then-diversify |
| 1–10 integer scores beat binary for monitors | pAUROC 0.905 vs 0.269 | ✔ → §2.7 |
| A single reference solution suffices for non-interference | No — KernelBench: oracle never exercised `load_inline`; two over-restrictive defenses slipped through | ✖ → §2.1 requires ≥2 diverse solutions |
| The cross-verifier proof can use the same exploit that produced the patch | No — circular | ✖ → §4.3 re-derives from a held-out family on a different verifier |

### 9.2 Structural checks (mechanised)

[`verify_architecture.py`](verify_architecture.py) encodes the component graph from this document and asserts:

1. every artifact any component consumes is produced by some component
2. the pool has exactly one writer, and it is the Trial Runner (I2)
3. the ledger and `herd-audit` have only trusted writers, and no untrusted component holds their keys (I1)
4. every path from a Fixer to the pool passes through the trial gate (I2)
5. every metric in §2.10 has a producing component and a held-out source where required (I5)
6. every demo beat in §8 reads an artifact that exists
7. the promotion gate's inputs are behavioural detectors only (§2.7)

Run: `python3 claude/verify_architecture.py` — exits non-zero on any violation and prints the offending edge.

### 9.3 Known open items

- **Stage 1.5 triage prior** is a heuristic; it affects trial ordering, not correctness.
- **`k=5` hosts and the ambiguous-band thresholds** for escalation are unvalidated defaults; tune on the first generation's data.
- **Cross-capability transfer** (`transfer_family` on hosts sharing few tags) may be small. It is reported regardless.
- **ARIA availability** cannot be tested off-site.
