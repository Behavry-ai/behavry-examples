# Meraki Alert Triage Agent: the code

The runnable agent for the [Meraki alert triage example](../README.md). Read the
example's guide first; this page covers setup, configuration and tests.

It is small on purpose, so your team can read all of it in an afternoon and
change what you need.

## Layout

| File | What it does |
| --- | --- |
| `meraki_triage/app.py` | Webhook endpoint, queue, and the worker that runs each alert |
| `meraki_triage/alerts.py` | Meraki payload parsing, shared-secret check, classification, instruction-like text detection |
| `meraki_triage/gate.py` | Noise gate: drops repeats, holds outages, cancels flaps |
| `meraki_triage/behavry_mcp.py` | Client for Behavry's MCP gateway, including held-call outcomes |
| `meraki_triage/triage.py` | The one model call per alert, through Behavry's Anthropic proxy |
| `meraki_triage/pipeline.py` | Lookup, triage, Halo writes, hand-off, and the approval-gated remediation |
| `meraki_triage/notes.py` | The text written into Halo |
| `meraki_triage/config.py` | Settings from environment variables |

## Before you run it

In Behavry:

- An agent identity for this agent, with its `client_id` and `client_secret`.
- Your MCP gateway (or Halo's MCP server directly) registered as a target. If
  it fronts several systems, mark it as a gateway so policy and the record can
  tell Halo calls from Meraki or RMM calls.
- A policy for this agent: reads allowed, Halo notes and tickets allowed, any
  device action held for approval. The example's guide has the table.

On your side:

- A Halo API user for the agent (for example "AI Technician").
- A sandbox Halo client or ticket type for the trial.
- A Meraki test network with a webhook receiver pointing at this agent.
- An Anthropic API key. Behavry's proxy forwards it to Anthropic and never
  logs it.

## Configuration

All settings are environment variables. Keep the secrets in your platform's
secret store.

| Variable | Required | What it is |
| --- | --- | --- |
| `BEHAVRY_PROXY_URL` | yes | Your Behavry plane, for example `https://<your-plane>.behavry.ai` |
| `BEHAVRY_CLIENT_ID` / `BEHAVRY_CLIENT_SECRET` | yes | This agent's Behavry credentials |
| `ANTHROPIC_API_KEY` | yes | Forwarded upstream by Behavry, never logged |
| `MERAKI_SHARED_SECRET` | yes | The shared secret set on the Meraki webhook receiver |
| `GATEWAY_SERVER_ID` | recommended | The gateway's id in Behavry, so tools only come from it |
| `TOOL_<NAME>` | no | Override a tool name, for example `TOOL_ADD_ACTION=halo_add_action` |
| `HALO_SANDBOX_CLIENT_ID` | trial | Every ticket lands on this client |
| `HALO_NOTE_ACTIONTYPE_ID` | recommended | A private note action type |
| `HALO_TICKET_TYPE_ID` | no | Ticket type for new tickets |
| `HALO_ONCALL_AGENT_ID` / `HALO_ONCALL_TEAM` | recommended | Who gets tickets that need a person |
| `ALLOW_REMEDIATION_REQUESTS` | no | `true` in phase 2 to let the agent ask to reboot |
| `TRIAGE_MODEL` | no | Default `claude-opus-5-5` |
| `TRIAGE_EFFORT` | no | Default `medium` |
| `TRIAGE_MODEL_FALLBACKS` | no | Default `true`; server-side fallback if the model declines |
| `FLAP_HOLD_SECONDS` / `DEDUPE_WINDOW_SECONDS` | no | Default 300 and 900 |

Default tool names are `halo_search_assets`, `halo_list_tickets_by_client`,
`halo_create_ticket`, `halo_update_ticket`, `halo_add_action` and
`meraki_reboot_device`, with the arguments a typical Halo MCP server uses. On
startup the agent lists its tools through Behavry and stops with a clear
message if a required one is missing.

## Run it

```bash
pip install -r requirements.txt
uvicorn meraki_triage.app:app --host 0.0.0.0 --port 8080
```

To host it, build the image from this folder (`Dockerfile`) and run it behind
HTTPS on port 8080. Run **exactly one replica**: the noise gate keeps its state
in memory, and two replicas would each open a ticket. The webhook URL for
Meraki is `https://<your-host>/webhooks/meraki`. Health check: `GET /healthz`.

## Test it

```bash
pip install -r requirements-dev.txt
pytest
```

The tests cover alert classification, the shared secret, the noise gate,
Behavry's responses (allowed, refused, held then rejected, held then timed
out), the fenced prompt, concurrency, and the full pipeline including the
injection case.

## Things to know

- **Alert types.** Classification is by keyword on Meraki's alert type. Check
  it against real payloads from your networks (Meraki's "send test webhook"
  button) and extend `_RULES` in `alerts.py` if needed.
- **Halo shapes.** Halo list responses are read defensively (`_records` in
  `pipeline.py`). If your gateway reshapes them, adjust there.
- **Injection.** Alert fields that read like instructions are flagged, the
  ticket goes to a person, and no remediation is requested for that alert. The
  alert itself is still processed and recorded.
- **Approval waits.** A held call stays open until someone decides, up to 30
  minutes depending on the agent's risk tier. The client waits 31 minutes, and
  alerts run side by side (one at a time per device), so one pending approval
  never stalls the rest.
