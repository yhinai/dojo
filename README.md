# HERD

**One agent struggles. Every agent learns.**

HERD is a runnable shared learning system for tool-using agents. Five learners work on marimo tasks over three rounds, distill verified repairs into scoped lessons, and test candidate lessons on fresh workers before publishing an immutable shared skill pool.

The application includes a Docker notebook evaluator, 12 task families across five tracks, a durable worker budget, paired PACE-style admission, regression and composition controls, restartable scheduling, four final comparison arms, a reactive marimo control room, Weave evidence export and native evaluations, and an authentic manual ARIA report workflow. **No measured learning improvement is claimed until a live experiment completes.**

## Run locally

Requires Python 3.11+, [uv](https://docs.astral.sh/uv/), and Docker for generated code.

```bash
uv sync --frozen --extra dev --extra weave
uv run playwright install chromium
docker build -t herd-runtime:local .
cp .env.example .env
uv run herd preflight
uv run herd sponsor-baseline --publish-weave
```

Configure `WANDB_API_KEY`, `WANDB_PROJECT=entity/project`, and a random `HERD_CONTROL_TOKEN` in `.env`. The default worker is W&B Inference `deepseek-ai/DeepSeek-V4-Flash-0731`; the initial global inference cap is **$25**. The full protocol can pause before completion when this cap is exhausted. No credentials are committed or mounted into notebook containers. Different providers/models require explicit verified prices.

`herd preflight` performs local Docker, sandbox and Chromium readiness checks without paid inference. Measured workers check readiness before calling the provider. Generated notebook success requires headless behavior checks plus fresh browser startup and the registered interaction. The default test suite also runs Docker containment and browser integration checks; set `HERD_SKIP_RUNTIME=1` only on hosts that intentionally lack those runtimes.

```bash
uv run herd init                      # prints experiment ID; freezes baselines
uv run herd run EXPERIMENT_ID         # run/resume the complete protocol
uv run herd serve                     # local API on 127.0.0.1:8000
uv run herd control-room              # marimo dashboard on port 2718
```

The dashboard defaults to read-only demo mode. Set `HERD_DEMO_MODE=0` to enable authenticated start/resume controls. The local API and dashboard bind loopback. The supplied dedicated-host deployment adds authenticated reverse-proxy access and private API reads.

You can inspect the dashboard before configuring a model:

```bash
uv run herd serve --demo
uv run herd control-room
```

## Verify without paid model calls

```bash
uv run pytest -q
uv run marimo check app/control_room.py
uv run herd validate-fixtures
python3 claude/verify_architecture.py
```

`herd sponsor-baseline` is the live sponsor check. It authenticates W&B, initializes Weave, validates the configured inference model with a minimal completion, and checks marimo. ARIA and molab are reported as UI-verified integrations because neither supplies a separate API key.

Fixture validation runs real marimo reference and deliberately broken notebooks, but accepts only the exact registered fixtures outside Docker. It is not a learning experiment. `--browser` adds real browser interaction verification and requires installed Playwright Chromium.

## Experiment and evidence

- 45 development episodes: five learners × three rounds × three tasks.
- At most 15 candidate lessons, evaluated independently against their round-start pool, with up to 64 fresh pairs each.
- Admission threshold 20 at per-candidate alpha 0.05. The stricter familywise threshold 300 is reported separately. Ties add no evidence; invalid pairs consume the finite budget.
- Regression controls precede admission, and the proposed combined pool is checked before committing a new snapshot.
- Final comparison: 60 held-out tasks × three fresh repeats × four arms = 720 episodes. Arms are no pool, frozen curated docs, raw memory, and admitted pool. Reports include first-submission success, resource use, paired outcomes, and task-family bootstrap intervals.
- SQLite checkpoints, content hashes, traceable run IDs, and an append-only hash chain live under ignored `experiments/`. An incomplete or infrastructure-blocked run must not be presented as a completed result.

All arms receive the same task, worker budget, tools, and base documentation. Only the bounded memory envelope changes. The curated supplement and raw-memory selection rule are frozen before training. Final tasks never feed lesson generation or ARIA curriculum selection.

## Sponsor workflows

```bash
uv run herd sync-weave EXPERIMENT_ID
uv run herd aria-export EXPERIMENT_ID
uv run herd aria-import PATH_TO_BUNDLE PATH_TO_REPORT HTTPS_ARIA_URL OPERATOR CURRICULUM_ACTION
```

Weave uploads durable evidence, reconstructs native evaluations from recorded oracle outcomes, and publishes a real leaderboard reference when configured. Recorded evaluation replay is labeled distinctly from source worker execution. ARIA uses an operator-attested report from the genuine W&B interface; no undocumented API or fabricated report is used. The molab packaging workflow and provider-neutral inference contract are implemented; actual hosted/provider validation requires sponsor access and documented compatibility.

## Design and build documentation

- [Build and verification status](docs/BUILD_STATUS.md)
- [Demo runbook](docs/DEMO_RUNBOOK.md)
- [Idea and assessment](claude/HERD.md)
- [Complete architecture](claude/ARCHITECTURE.md)
- [Statistical protocol](claude/GENERALITY.md)
- [Full build plan](claude/BUILD_PLAN.md)
- [Protocol defaults](claude/protocol.json)
- [Research catalog](docs/papers.md)

Historical proposals remain in the repository and do not override the active shared-learning protocol.

## Completion workflows

The remaining local workflows are now implemented, including audited lesson lifecycle changes, semantic curation, plausible false-lesson controls, versioned ARIA curriculum application, complete request-ledger accounting, operational recovery, and a single-operator deployment package. See [BUILD_STATUS.md](docs/BUILD_STATUS.md) for the distinction between implemented behavior and credential-gated execution.

```sh
uv run herd calibrate EXPERIMENT_ID       # real worker calibration, no lesson generation
uv run herd control EXPERIMENT_ID pause  # takes effect at worker checkpoints
uv run herd lifecycle EXPERIMENT_ID retract 'Observed regression' --lesson-ids LESSON_ID
uv run herd control EXPERIMENT_ID resume
uv run herd run EXPERIMENT_ID
uv run herd accounting EXPERIMENT_ID --output /path/to/accounting.json
uv run herd health
```

Lifecycle actions `retract`, `rollback`, `supersede`, and `resolve_conflict` are audited and applied at a future round boundary after behavioral controls. They cannot alter the final frozen comparison. Rollback requires `--target-pool-hash`; supersession requires an admitted `--replacement-id` and `--lesson-ids` identifying the current lesson.

ARIA import can queue an actual curriculum change with `--track-weights '{"0":1,"1":1,"2":3,"3":1,"4":1}'`. All five tracks remain represented; subsequent development assignments consume the versioned weights. Admission/final samplers remain fixed. Run import before the next development round starts.

Uncertain provider requests retain their reservation. Inspect `/api/experiments/EXPERIMENT_ID/budget` or the accounting report; use `herd reconcile REQUEST_ID ACTUAL_USD EVIDENCE OPERATOR` only with a real billing receipt. Add `--authorize-retry` if a new billed generation is intended. A retry retains the old charge and receives a distinct physical request ID; it is never an automatic assumption that the previous call was free.

Reconciliation alone does not authorize another model call. You can later repeat reconciliation with the same actual charge and `--authorize-retry` to append the retry authorization, then resume the experiment. The original receipt and charge remain in the audit history.

The service and `herd run` continuously sweep durable records into the Weave outbox and retry authentic uploads when configured. `sync-weave` remains an explicit recovery command. Native evaluations are recorded oracle replays, not repeated model executions. Fixture experiments are excluded from remote measured evidence.

For another provider, supply its documented HTTPS OpenAI-compatible endpoint, model ID and verified token prices, set `HERD_PROVIDER_NAME`, and run `herd provider-check`. No proprietary endpoint is guessed. A provider with a different wire protocol needs a documented adapter before it can be claimed as supported. Changing providers starts a separately bound experiment.

[Deployment instructions](deploy/README.md) include Linux services, authenticated Caddy proxy, secret files, backup/restore, health monitoring and a molab control-room package. Build that package with `uv run python scripts/package_molab.py /new/output/directory`. Public hosting, actual sponsor account validation, live experiment results and recordings still require execution and access.

## Calibrate and inspect readiness

Run `herd calibrate EXPERIMENT_ID` before training. Its assessment reports actual first-submission success, an explicit >85% success warning, and measured episode cost/latency projected over the complete workload. A 30–50% first-attempt failure rate is a task-design target, never a manufactured result. Auxiliary distillation/curation costs are separately identified estimates until those calls execute. The $25 default is a spending ceiling; use measured calibration to choose an appropriate allowance.

`/api/health` reports liveness. `/api/readiness` reports database health, worker/provider configuration, Docker-image availability and actual cached Chromium-launch readiness separately; unavailable dependencies return HTTP 503. Authenticated `/api/experiments/ID/attempts?offset=0&limit=100` and `/events?after=0&limit=100` provide bounded pages; `/attempts/RUN_ID` loads full code/conversation evidence only when requested. The dashboard uses these endpoints and a manual full-report load control.

The opening demo beat has a source: `/api/experiments/ID/failure-clusters` groups actual round-one first-submission failing checks across learners. `scripts/assemble_demo.py` exports the same data as `round-one-failure-clusters.json` with run IDs. A missing first submission remains missing evidence.

Live Weave operations initialize for either `HERD_WEAVE_PROJECT` or `WANDB_PROJECT`; actual paired results also enter `EvaluationLogger` during execution. The outbox's separately labeled replay supports recovery. Set `HERD_TRACE_CONVERSATIONS=1` to include redacted worker conversations; the default omits conversation content. Never include credentials in worker prompts.
