# CoreWeave Hacks sponsor setup

Verified September 12, 2026 using Chrome. Account: yahya.s.alhinai@gmail.com.

## Team access

- Nihal Nihalani (`nihal.nihalani@gmail.com`, GitHub `nihalnihalani`) was added to the W&B `yahya-dojo-hacks` team with full Models and Weave access. W&B only enabled the Admin role for this team; Member and View-Only were disabled in the role picker.
- GitHub write access to `yhinai/dojo` was granted to `nihalnihalani`.
- Molab's workspace reports 10 seats but exposes no member-invite control in the current workspace UI. Notebook sharing currently offers URLs and a live read-only view, not editable collaborator access.
- TypeSafe remains invite-only for the primary account, so it cannot accept collaborators yet. Hackathon credit provisioning is participant-specific and must be completed by TypeSafe staff.

## Claims and access

| Product | Offer / current state | Remaining step |
| --- | --- | --- |
| W&B Inference | Gateway enabled; API verified with 28 models; activation request emailed to Anna | Billing UI still shows the normal $2 allowance, so the $100 quota update remains pending |
| TypeSafe AI | Credit form submitted; Google sign-in completed; public waitlist joined | Console remains invite-only; a TypeSafe representative must provision model/API access |
| Weave | Current Free plan includes 1 GB monthly ingestion | API credential authenticates; real trace verified in `yahya-dojo-hacks/dojo` |
| marimo / molab | Handbook advertises free cloud GPUs | MFA completed; signed-in notebook created; RTX Pro 6000 (Blackwell) configuration saved, GPU execution not yet tested |
| ARIA | W&B in-app research assistant; no separate credit grant/API key listed | Working in private project `yahya-dojo-hacks/dojo` |
| W&B Training | Billing shows $500 allowance | Observed allowance only; training availability not tested |
| Fully Connected | Conditional conference-ticket opportunity | Ask CoreWeave staff for attendee qualification criteria; not an automatic credit |

Luma says registration approved and event September 12–13. Handbook schedule contains stale June dates; use the event listing for dates.

## Credentials

New key name: `dojo-coreweave-hacks-2026-09-12`, organization `nihalnihalani`.
Stored in repository-root `.env.hackathon`, mode 0600, ignored by Git. Never commit or print it.
W&B GraphQL verified the authenticated username `yahya-s-alhinai` and correct email.
Inference is now enabled and its API returned 28 available models. The billing page still showed the default $2 allowance when checked, so the advertised $100 hackathon quota remains pending.
TypeSafe's console accepts Google sign-in for `yahya.s.alhinai@gmail.com` but reports that the account is invite-only. The public waitlist submission succeeded. Two messages to the website-listed `hello@typesafe.ai` address bounced because the recipient group does not exist or does not accept posts; use the event organizer or an on-site TypeSafe representative for provisioning.

## Local tools

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
