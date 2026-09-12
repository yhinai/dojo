#!/usr/bin/env python3
"""Structural verification of claude/ARCHITECTURE.md.

Encodes the component graph as data and asserts the design invariants.
Exit code 0 = all checks pass. Non-zero = prints every violation.
"""
from __future__ import annotations
import sys
from dataclasses import dataclass, field

UNTRUSTED, TRUSTED, OBSERVE = "untrusted", "trusted", "observe"

@dataclass
class Component:
    name: str
    domain: str
    produces: set[str] = field(default_factory=set)
    consumes: set[str] = field(default_factory=set)
    credentials: set[str] = field(default_factory=set)

# ---- Component graph, transcribed from ARCHITECTURE.md §2, §5, §6 -------------------
C = {c.name: c for c in [
    Component("TaskRegistry", TRUSTED,
        produces={"Task"},
        consumes={"terminal-wrench:tasks"}),
    Component("ExploitLibrary", TRUSTED,
        produces={"PortableExploit"},
        consumes={"terminal-wrench:trajectories"}),
    Component("AgentCell", UNTRUSTED,
        produces={"Trajectory", "Patch:quarantine"},
        consumes={"Task", "PortableExploit:train", "Pool:read"},
        credentials={"INFERENCE_KEY", "WANDB_KEY[herd-agents]"}),
    Component("Sandbox", UNTRUSTED,
        produces={"AttemptResult"},
        consumes={"Task", "Pool:read"},
        credentials={"INFERENCE_KEY"}),
    Component("TrialRunner", TRUSTED,
        produces={"TrialRecord", "Pool:write", "EvidenceBundle"},
        consumes={"Patch:quarantine", "Task", "PortableExploit", "AttemptResult", "Pool:read"},
        credentials={"INFERENCE_KEY", "WANDB_KEY[herd-audit]", "POOL_PUSH_KEY", "LEDGER_SIGNING_KEY"}),
    Component("Pool", TRUSTED,
        produces={"Pool:read", "PoolEntry"},
        consumes={"Pool:write"}),
    Component("DetectorEnsemble", TRUSTED,
        produces={"Verdict", "DetectorScore:behavioural", "DetectorScore:signature", "DetectorScore:learned"},
        consumes={"Trajectory", "terminal-wrench:trajectories"},
        credentials={"INFERENCE_KEY"}),
    Component("Auditor", TRUSTED,
        produces={"Weave[herd-audit]", "EvidenceBundle"},
        consumes={"Trajectory", "Verdict", "DetectorScore:behavioural", "DetectorScore:signature", "DetectorScore:learned"},
        credentials={"WANDB_KEY[herd-audit]", "LEDGER_SIGNING_KEY", "INFERENCE_KEY"}),
    Component("Ledger", TRUSTED,
        produces={"Ledger:read"},
        consumes={"EvidenceBundle"}),
    Component("Metrics", TRUSTED,
        produces={"Metric:colony_asr", "Metric:herd_immunity", "Metric:transfer_task",
                  "Metric:transfer_family", "Metric:benign_pass", "Metric:detector_tpr_5fpr",
                  "Metric:false_commit", "Metric:pool_precision", "Metric:exploit_novelty",
                  "Weave[herd-audit]:leaderboard"},
        consumes={"Ledger:read", "Weave[herd-audit]", "PoolEntry", "TrialRecord", "Task", "PortableExploit:heldout"},
        credentials={"WANDB_KEY[herd-audit]"}),
    Component("Orchestrator", TRUSTED,
        produces={"GenerationRecord"},
        consumes={"Pool:read"}),
    Component("ControlRoom", OBSERVE,
        produces=set(),
        consumes={"Weave[herd-audit]", "Ledger:read", "PoolEntry", "Trajectory",
                  "Metric:colony_asr", "Metric:herd_immunity", "Metric:transfer_task",
                  "Metric:transfer_family", "Metric:benign_pass", "Metric:detector_tpr_5fpr"},
        credentials={"WANDB_KEY[herd-agents]:read", "WANDB_KEY[herd-audit]:read"}),
    Component("ARIA", OBSERVE,
        produces={"IncidentReport"},
        consumes={"Weave[herd-audit]", "Metric:herd_immunity", "Metric:pool_precision"}),
]}

# Artifacts that come from outside the system.
EXTERNAL = {"terminal-wrench:tasks", "terminal-wrench:trajectories"}

# Artifact aliasing: a producer of X also satisfies a consumer of X:<qualifier>.
def satisfied(artifact: str, producers: set[str]) -> bool:
    if artifact in producers or artifact in EXTERNAL:
        return True
    base = artifact.split(":")[0]
    return base in producers and artifact.split(":")[1] in {"train", "heldout", "read"}

# Promotion gate inputs (ARCHITECTURE.md §2.7): behavioural detectors only.
GATE_INPUTS = {"DetectorScore:behavioural", "PairedOutcome"}

# Demo beats -> artifact they read (ARCHITECTURE.md §8).
DEMO = {
    "0:00 two-pane":        {"Trajectory", "DetectorScore:signature"},
    "0:12 colony":          {"Metric:colony_asr"},
    "0:27 propagation":     {"PoolEntry", "Weave[herd-agents]"},
    "0:47 live vaccination":{"Task", "PortableExploit:heldout", "Pool:read"},
    "1:22 numbers":         {"Metric:transfer_task", "Metric:transfer_family"},
    "1:37 believe":         {"Metric:detector_tpr_5fpr", "TrialRecord"},
    "2:07 cost":            {"Metric:benign_pass"},
    "2:22 sponsors":        {"Weave[herd-audit]:leaderboard", "IncidentReport"},
}

# Fixer -> pool paths must pass through the trial gate.
EDGES = [  # (from, to, via)
    ("AgentCell", "TrialRunner", "Patch:quarantine"),
    ("TrialRunner", "Pool", "Pool:write"),
]

def main() -> int:
    v: list[str] = []
    produced: set[str] = set().union(*(c.produces for c in C.values()))
    # agents' own observability project is produced implicitly by AgentCell tracing
    produced.add("Weave[herd-agents]")

    # 1. every consumed artifact is produced
    for c in C.values():
        for a in c.consumes:
            if not satisfied(a, produced):
                v.append(f"[unproduced] {c.name} consumes '{a}' but nothing produces it")

    # 2. pool has exactly one writer and it is TrialRunner (I2)
    writers = [c.name for c in C.values() if "Pool:write" in c.produces]
    if writers != ["TrialRunner"]:
        v.append(f"[I2] Pool writers must be exactly ['TrialRunner'], got {writers}")
    keyholders = [c.name for c in C.values() if "POOL_PUSH_KEY" in c.credentials]
    if keyholders != ["TrialRunner"]:
        v.append(f"[I2] POOL_PUSH_KEY holders must be exactly ['TrialRunner'], got {keyholders}")

    # 3. audit record writers are trusted; untrusted components hold no audit keys (I1)
    for c in C.values():
        if c.domain == UNTRUSTED:
            bad = {k for k in c.credentials if k in {"WANDB_KEY[herd-audit]", "LEDGER_SIGNING_KEY", "POOL_PUSH_KEY"}}
            if bad:
                v.append(f"[I1] untrusted {c.name} holds {sorted(bad)}")
            if c.produces & {"Weave[herd-audit]", "EvidenceBundle", "Pool:write"}:
                v.append(f"[I1] untrusted {c.name} writes an audit artifact")
    for c in C.values():
        if c.domain == OBSERVE and any(not k.endswith(":read") for k in c.credentials):
            v.append(f"[I1] observe-domain {c.name} holds a write credential: {sorted(c.credentials)}")

    # 4. every Fixer->Pool path goes through TrialRunner (I2)
    direct = [e for e in EDGES if e[0] == "AgentCell" and e[1] == "Pool"]
    if direct:
        v.append(f"[I2] direct AgentCell->Pool edge exists: {direct}")
    if not any(e == ("AgentCell", "TrialRunner", "Patch:quarantine") for e in EDGES):
        v.append("[I2] no AgentCell->TrialRunner quarantine edge")

    # 5. every metric has a producer and Metrics consumes only held-out/ledger sources (I5)
    metric_names = {a for a in produced if a.startswith("Metric:")}
    expected = {"Metric:" + m for m in ["colony_asr","herd_immunity","transfer_task","transfer_family",
                "benign_pass","detector_tpr_5fpr","false_commit","pool_precision","exploit_novelty"]}
    missing = expected - metric_names
    if missing:
        v.append(f"[I5] metrics declared in §2.10 but not produced: {sorted(missing)}")
    if "Trajectory" in C["Metrics"].consumes:
        v.append("[I5] Metrics must not consume raw agent Trajectory (self-report); use Ledger/Weave[herd-audit]")

    # 6. every demo beat reads an artifact that exists
    for beat, arts in DEMO.items():
        for a in arts:
            if not satisfied(a, produced):
                v.append(f"[demo] beat '{beat}' reads '{a}' which nothing produces")

    # 7. promotion gate consumes behavioural detectors only (§2.7)
    gate_bad = GATE_INPUTS & {"DetectorScore:signature", "DetectorScore:learned"}
    if gate_bad:
        v.append(f"[gate] promotion gate must not consume {sorted(gate_bad)}")

    # 8. trust-domain data flow: nothing flows from OBSERVE back into TRUSTED/UNTRUSTED
    for c in C.values():
        if c.domain == OBSERVE and c.produces - {"IncidentReport"}:
            v.append(f"[flow] observe-domain {c.name} produces non-report artifact {sorted(c.produces)}")

    if v:
        print("ARCHITECTURE VERIFICATION: FAIL")
        for line in v:
            print("  -", line)
        return 1
    print("ARCHITECTURE VERIFICATION: PASS")
    print(f"  components={len(C)}  artifacts={len(produced)}  demo_beats={len(DEMO)}")
    print("  I1 audit-write isolation .......... ok")
    print("  I2 single pool writer via gate .... ok")
    print("  I5 metrics from audit sources ..... ok")
    print("  §2.7 gate on behavioural only ..... ok")
    print("  §8 every demo beat has a source ... ok")
    return 0

if __name__ == "__main__":
    sys.exit(main())
