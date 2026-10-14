<p align="center">
  <img src="brand/behavry-horizontal-onwhite.svg" alt="Behavry" width="320">
</p>

<h1 align="center">Behavry Examples</h1>

<p align="center">
  Working reference agents, governed end to end by Behavry.<br>
  Each one comes with a guide you can hand to a team and code you can run.
</p>

---

Behavry is the system of record for autonomous agents. It sits between an
agent and every system it touches, binds each action to an identity, and
reconstructs what happened into a signed **Decision Trace**. Because it is in
the path, it can also permit, redact, hold or block an action against policy.

This repository shows what that looks like in real workflows. Every example
is a complete, small agent that does a useful job, with the decisions that
make it trustworthy written down next to the code.

## Examples

| Example | What the agent does | Systems | Guide | Code |
| --- | --- | --- | --- | --- |
| [Meraki Alert Triage](examples/meraki-alert-triage/) | Triages network alerts, writes a structured note to the PSA ticket, and asks a technician before it touches a device | Cisco Meraki, Halo PSA, an MCP gateway, Claude | [PDF](examples/meraki-alert-triage/guide.pdf) | [Python](examples/meraki-alert-triage/agent/) |

## What every example includes

```
examples/<name>/
  README.md      one-page overview: what it shows, systems, Behavry features used
  guide.md       the guide, written for the team that will run it
  guide.pdf      the same guide as a branded PDF, ready to share
  diagram.svg    how the agent's calls flow through Behavry
  agent/         the runnable code, with its own README, tests and Dockerfile
```

Each guide follows the same arc: what the example proves, how to scope a first
trial, how the agent is built and why, the policy it runs under, and how to
tell whether it worked.

## The patterns they share

The examples differ in what they automate. They share a few rules that make an
agent's work something a client, an auditor or your own team can rely on:

- **Every call goes through Behavry.** Model calls go through Behavry's model
  proxy and tool calls through its MCP gateway, so the record has no gaps.
- **One label per run.** Each piece of work (an alert, a request, a ticket)
  carries a run label on every call, so it reads as one Decision Trace.
- **The agent has its own identity,** in Behavry and in every system it uses,
  so its actions are attributable and it can be paused on its own.
- **Untrusted input stays data.** Text from outside is fenced in the prompt,
  the model returns fixed fields, and the agent's code, not the model, decides
  which tools to call.
- **Actions wait for a person.** Anything that changes a system the agent does
  not own is held by policy until someone approves it, and the outcome is
  recorded either way.

## Run an example

Each example's `agent/README.md` has its setup. In general you need:

1. A Behavry plane and an agent identity (`client_id` and `client_secret`).
2. The target systems registered in Behavry, with a policy for the agent.
3. The credentials the example names, kept in your secret store.

Then:

```bash
cd examples/<name>/agent
pip install -r requirements-dev.txt
pytest
```

Every example's tests run without any live system, so you can read and change
the code before connecting anything.

## Build the PDFs

The PDFs are generated from each `guide.md`, so the guide and the PDF never
drift apart.

```bash
pip install -r tools/pdf/requirements.txt
python -m playwright install chromium   # skip if Google Chrome is installed
python tools/pdf/build.py examples/*/guide.md
```

## Contributing

New examples and improvements are welcome. See
[CONTRIBUTING.md](CONTRIBUTING.md) for the layout an example needs and the
checks it must pass.

## Security

Please report a security issue privately to security@behavry.ai rather than in
a public issue. These examples are references: review them, and run them
against test systems first, before you point them at anything that matters.

## License

[Apache 2.0](LICENSE). The Behavry name and logo are trademarks of Behavry and
are not covered by the license.
