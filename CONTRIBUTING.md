# Contributing an example

An example earns its place when it does a real job, shows a governance
decision someone would actually face, and is small enough to read in an
afternoon.

## Layout

```
examples/<kebab-case-name>/
  README.md      overview: one-line summary, a facts table (guide, code,
                 systems, Behavry features), what it shows, how to run it
  guide.md       front matter (title, subtitle, category), then the guide
  guide.pdf      built from guide.md with tools/pdf/build.py
  diagram.svg    the call flow, in the brand palette
  agent/         code, README, tests, Dockerfile, requirements
```

## The guide

Write for the team that will run the agent, not for us. Follow the arc the
existing guides use: what it proves, how to start narrow, how the agent is
built and why, the policy table, and how to know it worked.

House style:

- Lead each section with its point. Short sentences, plain words.
- "Decision Trace" is always capitalised.
- Behavry is "the system of record for autonomous agents". Do not call it an
  AI security product, an AI SIEM, or a blocker.
- No em dashes.

## The code

- Every model call goes through a Behavry provider proxy and every tool call
  through Behavry's MCP gateway. No direct calls to the target systems.
- Every call for one unit of work carries the same `X-Behavry-Run-Id`.
- Untrusted input is fenced as data; the model returns structured output and
  the code chooses tools.
- Actions that change another system are written to be held for approval, and
  the code handles approved, rejected and timed-out outcomes.
- Tests run with no live system and cover those behaviours. Add the example
  to `.github/workflows/examples.yml`.

## Before you open a pull request

- [ ] No client, customer or partner names anywhere: code, comments, test data,
      the guide, the PDF or the diagram. Use generic names ("Acme Clinic").
- [ ] No real hostnames, tenant ids, credentials or tokens.
- [ ] `guide.pdf` rebuilt from the final `guide.md`.
- [ ] Tests pass.
