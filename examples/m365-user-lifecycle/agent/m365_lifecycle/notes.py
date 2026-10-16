"""The text the agent writes on the PSA ticket.

Three notes per request at most: the plan before anything runs, the outcome
of every step after, and (instead of both) the reason it stopped. No password,
token or secret is ever written: the account is created without one passing
through the agent.
"""
from __future__ import annotations

from html import escape

from m365_lifecycle.plan import Plan

SIGNATURE = "AI Technician (automated account changes, governed by Behavry)"

OUTCOME_WORDS = {
    "done": "done",
    "rejected": "not done: a reviewer rejected it in Behavry",
    "timed_out": "not done: no one approved it in time",
    "refused": "not done: policy does not allow it",
    "failed": "not done: the system reported an error",
    "skipped": "skipped: an earlier step did not complete",
    "unknown": ("still waiting for a decision in Behavry when the connection closed; if it is "
                "approved it will run, so check the approval queue before doing it by hand"),
}


def _head() -> str:
    return f"<p><em>{escape(SIGNATURE)}</em></p>"


def _list(items: list[str]) -> str:
    return "<ul>" + "".join(f"<li>{escape(i)}</li>" for i in items) + "</ul>"


def plan_note(plan: Plan) -> str:
    who = escape(plan.upn or "")
    held = [s.label for s in plan.steps if s.kind in {"grant", "wind_down"}]
    parts = [
        _head(),
        f"<p><strong>Planned {plan.kind} steps for {who}:</strong></p>",
        _list([s.label for s in plan.steps]),
        "<p>Steps that give or change access wait for a person to approve them in Behavry"
        + (f" ({escape(', '.join(held))})." if held else ".") + "</p>",
    ]
    if plan.for_person:
        parts += ["<p><strong>For a technician to decide (not done by the agent):</strong></p>",
                  _list(plan.for_person)]
    return "".join(parts)


def stopped_note(plan: Plan, request_id: str) -> str:
    parts = [_head(), "<p><strong>Nothing was changed.</strong> A technician needs to look at this request:</p>",
             _list(plan.problems)]
    if plan.for_person:
        parts += ["<p>Also asked for:</p>", _list(plan.for_person)]
    parts.append(f"<p><small>Request {escape(request_id)}</small></p>")
    return "".join(parts)


def refused_note(request_id: str, reason: str) -> str:
    """Written when Behavry refused a note. Carries no form-derived text."""
    return (_head() + f"<p><strong>Needs review:</strong> Behavry blocked the agent's note on this "
            f"request: {escape(reason)}. The form's text was left out on purpose. Review the request "
            "and its Decision Trace in Behavry.</p>"
            + f"<p><small>Request {escape(request_id)}</small></p>")


def outcome_note(plan: Plan, outcomes: list[tuple[str, str]], request_id: str) -> str:
    rows = [f"{label}: {OUTCOME_WORDS.get(o, o)}" for label, o in outcomes]
    tail = ""
    if plan.kind == "joiner" and any(o == "done" for label, o in outcomes if label.startswith("Create")):
        tail = ("<p>The account is created with sign-in off. On the start date, a technician "
                "turns sign-in on and issues a Temporary Access Pass.</p>")
    return (_head() + f"<p><strong>Outcome for {escape(plan.upn or '')}:</strong></p>" + _list(rows) + tail
            + f"<p><small>Request {escape(request_id)}</small></p>")
