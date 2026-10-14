# Microsoft 365 User Lifecycle Agent: the code

The runnable agent for the [Microsoft 365 user lifecycle example](../README.md).
Read the example's guide first; this page covers setup, configuration and
tests.

## Layout

| File | What it does |
| --- | --- |
| `m365_lifecycle/app.py` | Signed request endpoint, repeat-delivery check, and the worker that runs each request |
| `m365_lifecycle/intake.py` | The request model, the signature check, and the client catalogue |
| `m365_lifecycle/extract.py` | The one model call per request: reads the form into fixed fields, through Behavry |
| `m365_lifecycle/plan.py` | Turns those fields into steps using only the catalogue, and stops anything it cannot verify |
| `m365_lifecycle/pipeline.py` | Writes the plan, runs each step through Behavry, records every outcome |
| `m365_lifecycle/notes.py` | The text written on the PSA ticket |
| `m365_lifecycle/behavry_mcp.py` | Client for Behavry's MCP gateway, including held-call outcomes |
| `catalog.example.json` | A sample client catalogue (fictional) |

## Before you run it

In Behavry:

- An agent identity for this agent, with its `client_id` and `client_secret`.
- Your tool gateway registered as a target and marked as a gateway, so policy
  and the record can tell Microsoft 365 calls from PSA calls.
- The policy in [`../../../policies/`](../../../policies/): reads, standard
  groups and leaver lock-out allowed; account creation, mailbox conversion and
  licence removal held; directory roles and deletion refused.

On your side:

- Microsoft 365 tools behind your gateway that match the contract in
  `config.py` (`ToolNames`). The one hard rule: `m365_create_user` sets the
  initial password on the server and never returns it.
- A PSA automation that posts new-starter and leaver tickets to this agent,
  signed with HMAC-SHA256 (see below).
- Your client catalogue, kept by the MSP, never by the client.
- An Anthropic API key. Behavry's proxy forwards it to Anthropic and never
  logs it.

## The request

```http
POST /requests
X-Signature-256: sha256=<hex HMAC-SHA256 of the raw body with WEBHOOK_SECRET>
Content-Type: application/json

{
  "request_id": "REQ-1001",
  "ticket_id": 7001,
  "client_id": 40,
  "kind": "joiner",
  "form": "New starter: Riley Chen, Clinical, Nurse, starts 2026-11-02, manager sam.rivera@acmeclinic.example"
}
```

`form` can be text or an object of form fields. A repeated `request_id` is
accepted and ignored, so your PSA can retry safely.

## Configuration

| Variable | Required | What it is |
| --- | --- | --- |
| `BEHAVRY_PROXY_URL` | yes | Your Behavry plane, for example `https://<your-plane>.behavry.ai` |
| `BEHAVRY_CLIENT_ID` / `BEHAVRY_CLIENT_SECRET` | yes | This agent's Behavry credentials |
| `ANTHROPIC_API_KEY` | yes | Forwarded upstream by Behavry, never logged |
| `WEBHOOK_SECRET` | yes | The HMAC key your PSA signs requests with |
| `CLIENT_CATALOG_PATH` | yes | Path to your client catalogue (JSON, see `catalog.example.json`) |
| `GATEWAY_SERVER_ID` | recommended | The gateway's id in Behavry, so tools only come from it |
| `TOOL_<NAME>` | no | Override a tool name, for example `TOOL_CREATE_USER=graph_create_user` |
| `HALO_NOTE_ACTIONTYPE_ID` | recommended | A private note action type |
| `LIFECYCLE_MODEL` | no | Default `claude-opus-5-5` |
| `LIFECYCLE_EFFORT` | no | Default `medium` |
| `LIFECYCLE_MODEL_FALLBACKS` | no | Default `true`; server-side fallback if the model declines |

## Run it

```bash
pip install -r requirements.txt
uvicorn m365_lifecycle.app:app --host 0.0.0.0 --port 8080
```

To host it, build the image from this folder and run it behind HTTPS. Run one
replica, because repeat deliveries are tracked in memory. Health check:
`GET /healthz`.

## Test it

```bash
pip install -r requirements-dev.txt
pytest
```

The tests cover the signature, the plan rules (names from the catalogue,
unknown departments, addresses outside the client, early leavers, extra
requests, suspicious forms), the fenced prompt, and the full pipeline:
approvals, rejections, timeouts, an existing account, an unknown leaver, and
repeat deliveries.
