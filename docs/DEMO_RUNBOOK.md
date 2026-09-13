# HERD demonstration runbook

This is an operational shot plan, not a record of a completed learning experiment. Model execution, sponsor access, authentic demonstration pair, live slider rehearsal, and final videos remain pending until their evidence exists. Do not insert fixture scores into a measured presentation.

## Prepare and freeze

1. Run preflight and resolve provider, price, budget, isolation, browser and W&B blockers. Preserve the execution manifest.
2. Register one `demonstration` task **before inspecting its results**. Use a real interaction task with a named slider, expected changed-input behavior, and public instructions. Keep it separate from admission and final tasks.
3. Complete the five-learner/three-round run. Freeze the final pool, retrieval and worker configuration.
4. Execute two fresh workers on the registered task: `no_pool` and `admitted_pool`, with the same task, repeat identity, tools, model and budgets; separate workspaces and histories. Record both even if both succeed, both fail, or the pool loses. A development repair is not this pair.
5. Run the full final four-arm comparison and retain its paired outcomes and family-clustered intervals.
6. Upload genuine evidence with `uv run herd sync-weave EXPERIMENT_ID`. Capture the returned Evaluation and Leaderboard references. Missing references remain pending.
7. Export real development summaries with `uv run herd aria-export EXPERIMENT_ID`; use the supported ARIA interface and import its actual report, URL, operator attribution and curriculum decision with `uv run herd aria-import --help` for arguments. Do not describe an API trigger that did not run.
8. Assemble read-only evidence:

```sh
uv run python scripts/assemble_demo.py EXPERIMENT_ID --task-id REGISTERED_DEMONSTRATION_TASK
HERD_DEMO_MODE=1 uv run herd control-room
```

The assembler does not choose a winning task. It records missing assets, rejects fixture experiments, and exports notebook source as text. It does not execute that source. `artifacts/demo/manifest.json` includes task/model/runtime bindings, original run IDs, lesson origins, gates, pools, pair outcomes, event hashes and report. Source files have content hashes. Copy the assembled directory into the presentation backup; do not include `.env`, credentials or private evaluator files.

## Three-minute shot script

| Time | Screen and evidence | Narration / action |
|---|---|---|
| 0:00–0:20 | Five learner cards, actual first-round diagnostics | “These agents are learning the same tool. Their mistakes are currently isolated.” If they did not share a failure family, describe the actual pattern. |
| 0:20–0:45 | One recorded attempt, first source, passing repair, exact lesson | Explain the mistake and the scoped lesson. Show origin and exclusions. Never use the incorrect claim that marimo cannot reference visually later cells. |
| 0:45–1:15 | Candidate stream, E, threshold, wins/losses/ties, controls | Explain evidence conditional on the registered task sampler. Threshold comes from the actual gate. Current per-candidate alpha and the familywise extension must not be conflated. |
| 1:15–1:30 | Actual false-lesson control and rejection reason | Explicitly label it an injected negative control. If no such record exists, this beat is pending. |
| 1:30–1:50 | Three-round timeline and pool snapshots | Label sped-up or recorded material. Show real contributors, recipient retrievals and snapshot hashes. An unchanged pool is a real result. |
| 1:50–2:25 | Predetermined fresh-worker pair, then live notebook | Distinguish recorded generation from live interaction. Move the slider and show the expected output changing. Describe both arms' actual results. |
| 2:25–2:45 | Four-arm report | State denominator, task-family interval, token use and total learning cost. If the pool only ties curated docs, say so. |
| 2:45–3:00 | Weave Evaluation, marimo control room, authentic ARIA contribution | Show sponsor artifacts that actually exist. Close on shared, tested experience. |

## Live interaction rehearsal

- Launch only the chosen, previously evaluated notebook through the candidate sandbox/broker on a reserved loopback port. The control room never imports candidate code.
- Keep evaluator data, control tokens, provider secrets and W&B credentials outside the notebook environment.
- Use the exact task-specific slider sequence from the registered public demonstration instructions; document initial and changed values beside observed outputs. Do not substitute a screen animation for recomputation.
- Rehearse startup, browser refresh, one interaction and cleanup twice. Record notebook hash, runtime hash, launch command, port, expected outputs, actual outcomes and duration in `artifacts/demo/rehearsal.json`.
- Confirm that demo controls are disabled and automatic refresh issues GET requests only. The live slider manipulates the candidate notebook, not experiment configuration.
- Keep the frozen report open separately; changing a display threshold cannot mutate admission decisions.

## Honest fallback and recording

Record the full three-minute path once authentic assets exist. Also edit a version shorter than two minutes for submission. Keep the complete recording as the network/browser failure fallback and label it “recorded run.” The current repository does not contain either recording.

If the admitted pool is empty, show the gate's insufficient-evidence outcome and the genuine no-pool comparison. If the chosen demonstration task does not improve, show that result; never silently switch to a flattering task. If the service is unreachable, the control room displays an explicit unavailable state. If Weave or ARIA access is blocked, identify the integration as unverified rather than using a guessed URL or invented report.

## Final asset checklist

- [ ] Actual five-learner first-round hook and diagnostics.
- [ ] Repair diff linked to a lesson and immutable admission stream.
- [ ] Genuine false-lesson control with rejection stage and reason.
- [ ] Three committed snapshot records, including unchanged snapshots.
- [ ] Predetermined demonstration pair with independent workers.
- [ ] Successful live slider rehearsal on the exact notebook and runtime.
- [ ] Four-arm final report, raw pairs, intervals and complete cost accounting.
- [ ] Actual Weave Evaluation / Leaderboard references and ARIA report/action.
- [ ] Demo mode verified read-only; manifest and source hashes archived.
- [ ] Three-minute recording, under-two-minute video, submission access and surveys.

## Generate the registered demonstration pair

After the final pool is frozen and credentials are configured:

```bash
uv run herd demo-probe EXPERIMENT_ID --seed 424242
uv run python scripts/assemble_demo.py EXPERIMENT_ID --task-id PRINTED_TASK_ID
```

Choose and retain the seed before seeing outcomes. The command runs independent no-pool and admitted-pool workers, then captures real browser verification when notebook source is available. It does not select a task based on success.

## Recovery and complete cost evidence

Before presentation, run `herd accounting EXPERIMENT_ID --output artifacts/demo/accounting.json`. The output covers all provider request stages, including distillation, curation and diagnostic controls. An unresolved reservation is not zero cost; keep total unknown until reconciled with a provider receipt. Use the recorded final frozen arm report for the comparison and the live all-stage ledger for subsequent demo/rehearsal costs.

False-lesson controls now run automatically before final evaluation and can be resumed explicitly with `herd false-controls EXPERIMENT_ID`. They use their own diagnostic streams; no diagnostic lesson enters the pool or consumes a primary candidate slot. Show actual `poisoning_control`, `control_gate` and `control_pair` records.

ARIA curriculum contribution must occur before a future round starts. The import command accepts `--track-weights` for all five tracks; show the imported source, queued version and next `round_curriculum` assignment record, not just an unexecuted suggestion.

For an outage, retain the checksummed offline state backup and assembled read-only evidence. Do not start original and restored state concurrently. The deployment runbook gives maintenance locking and staged restore commands. The molab package is generated by `scripts/package_molab.py`; a local package is not proof of a hosted session.
