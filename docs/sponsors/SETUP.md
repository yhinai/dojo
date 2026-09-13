# CoreWeave Hacks sponsor setup

Verified September 13, 2026 using Chrome and the live provider APIs. Account: yahya.s.alhinai@gmail.com.

## Team access

- Nihal Nihalani (`nihal.nihalani@gmail.com`, GitHub `nihalnihalani`) was added to the W&B `yahya-dojo-hacks` team with full Models and Weave access. W&B only enabled the Admin role for this team; Member and View-Only were disabled in the role picker.
- GitHub write access to `yhinai/dojo` was granted to `nihalnihalani`.
- Molab's workspace reports 10 seats but exposes no member-invite control in the current workspace UI. Notebook sharing currently offers URLs and a live read-only view, not editable collaborator access.
- TypeSafe remains invite-only for the primary account, so it cannot accept collaborators yet. Hackathon credit provisioning is participant-specific and must be completed by TypeSafe staff.

## Claims and access

| Product | Offer / current state | Remaining step |
| --- | --- | --- |
| W&B Inference | Working: authenticated listing returned 28 models and a minimal DeepSeek completion returned visible content | Confirm the advertised $100 quota in billing |
| TypeSafe AI | Credit form submitted; Google sign-in completed; public waitlist joined | Console remains invite-only; a TypeSafe representative must provision model/API access |
| Weave | Current Free plan includes 1 GB monthly ingestion | API credential authenticates; real trace verified in `yahya-dojo-hacks/dojo` |
| marimo / molab | Handbook advertises free cloud GPUs | Working: a hosted sandbox ran `nvidia-smi` on an RTX PRO 6000 Blackwell Server Edition with 97,887 MiB |
| ARIA | W&B in-app research assistant; no separate credit grant/API key listed | Working in private project `yahya-dojo-hacks/dojo` |
| W&B Training | Billing shows $500 allowance | Observed allowance only; training availability not tested |
| Fully Connected | Conditional conference-ticket opportunity | Ask CoreWeave staff for attendee qualification criteria; not an automatic credit |

Luma says registration approved and event September 12–13. Handbook schedule contains stale June dates; use the event listing for dates.

## Credentials

New key name: `dojo-coreweave-hacks-2026-09-12`, organization `nihalnihalani`.
Stored in repository-root `.env.hackathon`, mode 0600, ignored by Git. Never commit or print it.
W&B GraphQL verified the authenticated username `yahya-s-alhinai` and correct email.
Inference authentication requires the usage project in canonical `team/project` form. After correcting the application from `dojo` to `yahya-dojo-hacks/dojo`, the September 13 baseline listed 28 models and completed a real request with `deepseek-ai/DeepSeek-V4-Flash-0731`. The advertised $100 hackathon quota remains unconfirmed in billing.
TypeSafe's console accepts Google sign-in for `yahya.s.alhinai@gmail.com` but reports that the account is invite-only. The public waitlist submission succeeded. Two messages to the website-listed `hello@typesafe.ai` address bounced because the recipient group does not exist or does not accept posts; use the event organizer or an on-site TypeSafe representative for provisioning.

## Local tools

Run the secret-safe live baseline from the repository root:

```sh
uv sync --frozen --extra dev --extra weave
uv run herd sponsor-baseline --publish-weave
```

The command authenticates W&B, initializes and optionally publishes a real Weave object, lists the configured provider's models, makes a minimal completion, checks the local marimo control room, and reports the UI/manual boundaries for ARIA and molab. It checks TypeSafe automatically once `TYPESAFE_API_KEY`, `TYPESAFE_BASE_URL`, and `TYPESAFE_MODEL` are provisioned. It never prints credential values or model output.

Latest evidence: W&B authentication passed; Weave published `weave:///yahya-dojo-hacks/dojo/object/herd-sponsor-baseline:VGWnwGG36405n5fo1D0VfraX8LMv8dTcmXqihGYBbXc`; W&B Inference listed 28 models and returned visible content from a minimal completion; marimo validation passed; molab executed on the configured Blackwell GPU; and ARIA opened for the `dojo` project.

Installed global `wandb` 0.30.0, `marimo` 0.24.2, and official `wandb_mcp_server` 0.3.7.
W&B MCP source commit: `53b199a5f4af29aa82077e2c7f1e2c5e5e0c2ca0`.
Pinned its isolated dependency to `mcp<2` because the upstream code imports the v1 FastMCP API.
MCP server is installed but not registered with a coding-agent client.

Project `.venv` includes W&B, Weave 0.53.9, OpenAI SDK 3.13.0, marimo and recommended notebook dependencies.
Exact installed versions are in `requirements-hackathon.lock`.

```sh
source .venv/bin/activate
set -a
source .env.hackathon
set +a
marimo edit
```

Installed Codex skills (available next turn): `weave-integration`, `marimo-notebook`, `marimo-batch`, `anywidget`, `add-molab-badge`, `marimo-pair`.
Sources: handbook-recommended altryne/weavify-skill, official marimo-team/skills, official marimo-team/marimo-pair.

## Official references

- [Participant handbook](https://wandbai.notion.site/CoreWeave-Hacks-Participant-Handbook-3c9e2f5c7ef380eab21ecdde12620caf)
- [Credit request form](https://docs.google.com/forms/d/e/1FAIpQLSeTSFIuiOCGyAbQ3DpnCJaiyATkpDeOHdzD915QlH4J7x0CrQ/viewform)
- [Weave docs](https://docs.wandb.ai/weave)
- [Inference API](https://docs.wandb.ai/inference/api-reference)
- [ARIA overview](https://docs.wandb.ai/aria/overview)
- [ARIA governance](https://docs.wandb.ai/aria/governance)
- [marimo docs](https://docs.marimo.io/)
- [molab](https://molab.marimo.io/)
- [W&B MCP source](https://github.com/wandb/wandb-mcp-server)
- [TypeSafe](https://typesafe.ai/)
- [TypeSafe console](https://console.typesafe.ai/login)

Downloaded vendor reference snapshots accompany this file. Live docs remain authoritative.
