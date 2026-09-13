# HERD implementation status

This document describes executable code, not measured claims about agent learning.

## Implemented

| Area | Implementation |
| --- | --- |
| Contracts | Pydantic task, attempt, lesson, pool, pair, gate, event, and report models |
| Persistence | WAL SQLite state, compare-and-swap pool updates, append-only hash-chain events |
| Tasks | Five tracks, 12 registered families, partitioned deterministic generation, changed-input private probes, references and known negatives |
| Runtime | Real marimo App.run evaluation; Docker network denied, read-only root/source, non-root, CPU/memory/PID limits; development, calibration and demo use fresh browser startup/interaction checks; admission, regression and final use real headless behavioral probes |
| Workers | Fresh-context provider calls, bounded JSON actions, notebook repair, verified-repair-only distillation |
| Budget | Durable per-request reservation, verified model rates, unknown outcomes retained, global dollar cap |
| Memory | Scoped lesson schema, duplicate/unsafe-content rejection, runtime matching, fixed tag-based bounded retrieval |
| Admission | Bound paired e-process, duplicate rejection, finite 64-pair cap, 20 executed threshold and 300 diagnostic threshold |
| Scheduling | Five learners, three snapshot barriers, independent candidate trials, composition checks, durable resume |
| Final | Frozen four-arm evaluation with 720 planned episodes and clustered paired comparisons |
| UI | Reactive marimo dashboard, five learner cards, pool/evidence/results panels, read-only demo mode |
| Weave | Optional operation decorators, durable upload outbox, native recorded-result Evaluation/scorers and Leaderboard |
| ARIA | Development-only bundle export, actual report/URL import, operator attribution and curriculum action |
| Delivery | CLI, local FastAPI service, Dockerfile, locked dependencies, CI tests, demo assembly workflow |

## Execution prerequisites and limits

No model or W&B credentials were present during the original implementation pass. The current sponsor baseline has separately verified authenticated W&B/Inference access and a real Weave publish; live inference, an ARIA analysis, and a completed 720-episode comparison remain unexecuted. Empty dashboard metrics are intentional. Set credentials locally in `.env`; do not include secrets in evidence or commits.

`herd preflight` executes local runtime readiness checks without paid model calls. Measured workers check Docker image availability and sandbox readiness before inference. Development, calibration and demonstration additionally require Chromium readiness and browser startup/interaction checks on headless-passing submissions. Admission, regression and final evaluation use real headless probes without launching a browser per episode. The fixture-only validation command can still omit its additional browser checks unless `--browser` is selected.

The default $25 allowance is an initial inference cap, not a promise that the maximum-size experiment fits within $25. It excludes separate ARIA/hosting charges. The runtime and worker limits are enforced independently. Spend includes model calls for distillation; individual episode costs do not include that separate operation.

The registered tasks are synthetic marimo transfer tasks. Held-out compositions add unseen input conditions, but related operation families occur during development. Results support claims only about this registered task distribution, not arbitrary tools or general agent intelligence. A single learned pool does not estimate variability across entire learning runs.

Regression sentinels and poisoning checks reduce risk but do not prove universal safety or resistance to adversarial notebooks. Candidate code is isolated for execution and private expected outputs remain outside the container. Generated code must never use the trusted-reference execution mode.

The local API contains operational and code artifacts and is intended for loopback use. The supplied dedicated-host deployment supports authentication, secret files, persistent storage and backups. Multi-tenant authentication and managed remote storage are outside this single-operator architecture. No public deployment has been performed.

## Reproducible checks

```bash
uv sync --frozen --extra dev --extra weave
uv run pytest -q
uv run marimo check app/control_room.py
uv run herd validate-fixtures
uv run herd preflight
python3 claude/verify_architecture.py
```

Browser and Docker validations require those runtimes. Unit tests use explicit test workers where deterministic behavior is needed and never produce measured learning evidence.

## Historical local verification — before review remediation

The complete deterministic scheduler test exercises 45 development episodes, all 15 candidate slots, the three immutable round barriers, and all 720 final episodes. It uses `mode=test`; its outcomes are not empirical learning results. Resume of a completed experiment performs no extra worker calls.

Actual Docker tests pass all 12 held-out reference families and reject their negative controls. Containment probes verify non-root uid 65534, absence of provider-key environment variables, denied root-filesystem writes, and denied outbound TCP. Actual Chromium checks verify immediate slider reactivity and form changes remaining uncommitted until Apply. Local evidence lives in ignored `.herd/docker-test-*`, `.herd/browser-test-*`, and `.herd/browser-validation/report.json`.

The historical, now superseded tested immutable image was `sha256:b763ac378207e9e17f1beee2d7cbdf33959619bc54d23ede0984b200f81d4c73`. The CLI resolves the image tag to an immutable ID, combines it with the runtime/source/lock hash, and freezes that binding in each experiment. Colima was started for these tests; repository workspaces are mounted, while arbitrary host `/tmp` paths may not be.

Run the complete suite, including real containment and browser checks:

```bash
HERD_DOCKER_TESTS=1 HERD_BROWSER_TESTS=1 uv run pytest -q
```

## Completion pass — 2026-09-13

The following previously missing implementation paths have been added. The final repository-wide verification is recorded separately after independent review; this table does not claim that a real model experiment or hosted service has run.

| Requirement | Local implementation | Account-dependent execution |
| --- | --- | --- |
| Lesson removal and replacement | Audited retraction, ancestor rollback, admitted supersession and conflict resolution; behavioral controls at round boundaries; final freeze protected | Measure each change with the actual worker |
| Curator | Durable draft/rejection history, task-specific leakage checks and provider-backed semantic review of contradictions/leakage | Run semantic reviews on live drafts |
| False lessons | Plausible registered false packages through paired diagnostic gates; separate IDs and pool exclusion | Capture actual rejection/evidence outcomes |
| ARIA curriculum | Authentic report import plus versioned track weights consumed only by later development rounds | Obtain and import actual ARIA analysis |
| Accounting | Per-request ledger covers development, repair, distillation, curation, admission, controls, final, calibration and demonstration; unknown reservations and elapsed/episode time distinct | Provider usage reconciliation and external hosting/ARIA fees |
| Recovery | Shared/global execution locks, durable pause/cancel/resume, recorded billing reconciliation and explicitly authorized new retry generations | Resolve any actual unknown bill against provider records |
| Weave | Automatic durable-state sweep, content-addressed outbox, recovery, native recorded-result evaluations, leaderboard and authentic local links | Validate actual remote API authentication/upload references |
| Baselines | Common documentation plus a separate preauthored curated quick reference; configuration freezes both identities | Complete calibrated four-arm comparison |
| Deployment | Dedicated Linux systemd package, Caddy authentication, backend read protection, secret files, persistent state, checksummed staged restore, health and CI | Start on target Linux host, issue TLS and validate access |
| molab | Standalone control-room/requirements/setup/manifest exporter, authenticated remote API connection | Upload and verify hosted notebook with account access |
| TypeSafe | Documented provider-neutral OpenAI-compatible gateway and budgeted provider contract check; explicit provider identity | Confirm actual sponsor API compatibility, endpoint/model/pricing and credential access |
| Demo | Predetermined pair command, browser verification, evidence assembler and shot/runbook checklist | Generate authentic pair, rehearsals, recordings and submission assets |

Local targeted verification passed 19 delivery/report/integration tests, including real API process startup and authenticated reads, three-database plus artifact backup/restore, altered-backup rejection, unresolved/resumed billing accounting, pending outbox recovery and fixture exclusion. The official Caddy container validated the exact reverse-proxy configuration with network disabled; image digest `sha256:13ba145cba2f3e28fa801994876e4c086d1b95d5aa2a520a734765ffb6b12017`. The Linux CI workflow validates systemd units and repeats application/proxy checks. Linux service activation itself was not executed on the macOS development machine.

The application remains a dedicated single-operator system with a synthetic registered task distribution. Credential-free tests prove the implemented state transitions and runtime behavior; they do not establish learning improvement, statistical power under a real model, sponsor availability or production multi-tenancy.

## Historical independent verification — before review remediation

Independent review and the final repository-wide checks completed successfully:

- `HERD_DOCKER_TESTS=1 HERD_BROWSER_TESTS=1 uv run pytest -q`: **87 passed, 0 skipped**, in 29.99 seconds, with two upstream deprecation warnings.
- Ruff F checks across `src`, `tests`, and `scripts`: passed.
- `uv run marimo check app/control_room.py`: passed.
- `python3 claude/verify_architecture.py`: passed.
- Actual Docker and Chromium preflight: passed.
- Caddy container configuration validation and deployment shell syntax checks: passed.
- `git diff --check`: passed.

These results verify the credential-free implementation and real local runtime checks. The sponsor baseline separately records the live W&B/Weave/Inference checks; live learning, hosted deployment, and measured learning improvement remain unexecuted. No test-worker outcome is presented as a measured agent result.

## Review remediation — implementation and evidence boundaries

The review correctly identified task homogeneity, excessive browser work, transient-error handling, missing hook data, and calibration needs. Its statement that Weave initialized *only* during `sync-weave` was inaccurate: `make_engine` already initialized `WANDB_PROJECT`; initialization now also honors `HERD_WEAVE_PROJECT`. Actual execution additionally logs completed paired worker rows with the installed SDK's `EvaluationLogger`; the durable recorded-result replay remains separately labeled. Conversation tracing is opt-in through `HERD_TRACE_CONVERSATIONS=1`, with credential values redacted. A sponsor-baseline Weave object was subsequently published; this does not constitute a completed learning experiment or measured improvement.

API startup reconciles abandoned running states while holding the global scheduler lease. It cannot mark an active external CLI scheduler abandoned. Stop requests wait for that scheduler's checkpoint. `/api/health` is liveness; `/api/readiness` independently reports database health, engine/provider configuration, immutable Docker image availability and actual cached runtime preflight with Chromium launch. It returns HTTP 503 unless all checks pass; browser binary presence alone is insufficient.

Attempt lists and event trails are bounded pages. Full notebook source/conversation artifacts and final reports load on demand; the dashboard exposes attempt offsets and event cursors and labels its selected-page learner summaries. Round-one failure clusters use each attempt's preserved first submission, excluding infrastructure errors. The demo assembler exports the cluster evidence without inferring failures from successfully repaired terminal results.

Calibration reports measured first-submission rates, per-episode cost/latency and maximum-protocol workload projections, including control episodes and separately identified auxiliary-call assumptions. The 30–50% failure band is a design target, not a promised outcome; first-submission success above 85% triggers a warning. The default allowance is now $25, still a hard cap rather than a guarantee of completion.

CI has a deterministic subset job and a separate Docker/Chromium integration job. A local all-runtimes result must not be attributed to the subset CI job. Live calibration, statistical power and learning gains require actual model execution and are intentionally unclaimed.

## Current revision verification — 2026-09-13

The post-review runtime is bound to immutable image `sha256:dfbe4862ca0f3e613790d7965a22689e1bd19cd20769816282bbd94338b801f1`.

- `HERD_DOCKER_TESTS=1 HERD_BROWSER_TESTS=1 uv run pytest -q`: **119 passed, zero skipped**, in **64.58 seconds**, with two upstream deprecation warnings.
- After removing the redundant Playwright binary probe, the seven API tests passed again. A real `make_engine`/TestClient readiness smoke exited cleanly: Docker, Chromium launch and database checks passed; missing provider credentials correctly produced HTTP 503.
- Ruff F checks passed across source, tests and scripts. `marimo check`, architecture verification, deployment shell syntax, official Caddy configuration validation and `git diff --check` passed.
- Actual Docker/Chromium preflight passed. The dashboard loaded through Playwright with **zero page errors**.

Historical counts and image IDs above describe the earlier implementation. These checks establish local implementation and runtime behavior; live model calibration, sponsor uploads, learning gains and public deployment remain unexecuted. No calibration success rate or transferable-learning improvement has been manufactured.
