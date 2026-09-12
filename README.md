# HERD

**One agent struggles. Every agent learns.**

HERD is a proposed shared learning system for tool-using agents. Five learners work on marimo tasks over three rounds, turn verified repairs into scoped lessons, and test those lessons on fresh workers before publishing them to a shared skill pool.

## Active design

- [Idea and assessment](claude/HERD.md)
- [Complete architecture](claude/ARCHITECTURE.md)
- [Lesson admission and statistical protocol](claude/GENERALITY.md)
- [Astra/Fable build plan](claude/BUILD_PLAN.md)
- [Reference experiment defaults](claude/protocol.json)

The full target includes cross-agent trials, PACE-style gating, versioned retrieval and pooling, regression and poisoning controls, W&B Weave, a marimo control room, ARIA analysis, and a four-arm fresh-worker comparison.

## Current status

This repository contains research, architecture documents, and a reference protocol checker. It does **not** yet contain the implemented learning application or measured performance improvements.

Run the design checks:

```bash
python3 claude/verify_architecture.py
```

A passing check verifies selected protocol arithmetic and bookkeeping. It does not verify notebook behavior, sandbox isolation, statistical sampling assumptions, or sponsor integrations.

## Research and history

- [Research catalog](docs/papers.md)
- [Recent research](docs/freshest.md)
- [Earlier implementation research](docs/implementation.md)
- [Archived verifier-hardening HERD](claude/archive/verifier-herd-v1/README.md)
- [Historical DOJO proposal](astra.md)
- [Historical DOJO review](astra-review.md)

The previous projects and comparison notes are preserved. Their recommendations do not override the active shared-skill architecture.
