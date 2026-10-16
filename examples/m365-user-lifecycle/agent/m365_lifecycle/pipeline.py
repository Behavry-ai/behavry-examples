"""One joiner or leaver request, start to finish.

1. Find the client in the catalogue; read the form with the model.
2. Build the plan from the catalogue. If anything is wrong, write why on the
   ticket and stop: nothing is changed.
3. Write the plan on the ticket, then run each step through Behavry. Policy
   lets reads and leaver containment straight through and holds account
   creation and mailbox and licence changes for a person.
4. Write every step's outcome on the ticket. A rejection or a timeout is a
   result, never a reason to retry; a failed step that later steps depend on
   skips them.

Every call carries the request's run label, so the whole request reads as one
Decision Trace in Behavry.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from m365_lifecycle.behavry_mcp import BehavryMCP, GatewayError, GovernanceRefused, OutcomeUnknown, ToolFailed
from m365_lifecycle.config import Settings
from m365_lifecycle.extract import Extractor
from m365_lifecycle.intake import Catalog, LifecycleRequest
from m365_lifecycle.notes import outcome_note, plan_note, refused_note, stopped_note
from m365_lifecycle.plan import Plan, Step, build_plan

logger = logging.getLogger(__name__)

REQUIRED_TOOLS = (
    "get_user", "create_user", "assign_license", "add_group_member", "disable_user",
    "revoke_sessions", "convert_mailbox_to_shared", "remove_licenses", "ticket_note",
)


@dataclass
class Outcome:
    request_id: str
    run_label: str
    plan: Plan | None = None
    stopped: bool = False
    results: list[tuple[str, str]] = field(default_factory=list)  # (step label, outcome)


def run_label_for(req: LifecycleRequest) -> str:
    safe = "".join(c for c in req.request_id if c.isalnum() or c in "-_.")
    return f"{req.kind}-{safe}"[:128]


def _user_exists(data: Any) -> bool:
    return isinstance(data, dict) and data.get("found", True) is not False and bool(
        data.get("id") or data.get("userPrincipalName"))


class Pipeline:
    def __init__(self, settings: Settings, mcp: BehavryMCP, extractor: Extractor, catalog: Catalog,
                 *, today: Callable[[], date] = date.today) -> None:
        self._s, self._mcp, self._extractor, self._catalog, self._today = settings, mcp, extractor, catalog, today

    async def _note(self, out: Outcome, ticket_id: int, body: str) -> None:
        args: dict[str, Any] = {"ticket_id": ticket_id, "note": body, "send_email": False}
        if self._s.halo_note_actiontype_id is not None:
            args["actiontype_id"] = self._s.halo_note_actiontype_id
        try:
            await self._mcp.call("ticket_note", args, run_label=out.run_label)
        except GovernanceRefused as exc:
            # Behavry refused the note itself, for example because it quoted form
            # text it judged to be an injection. Write one note with no form text
            # instead, and never resend the refused content.
            logger.warning("request %s: Behavry refused a ticket note: %s", out.request_id, exc)
            args["note"] = refused_note(out.request_id, str(exc))
            try:
                await self._mcp.call("ticket_note", args, run_label=out.run_label)
            except GovernanceRefused:
                logger.error("request %s: Behavry refused the minimal note too", out.request_id)

    async def process(self, req: LifecycleRequest) -> Outcome:
        out = Outcome(request_id=req.request_id, run_label=run_label_for(req))
        try:
            await self._process(req, out)
        except GatewayError:
            logger.exception("request %s: Behavry gateway error", req.request_id)
        logger.info("request %s done: stopped=%s results=%s", req.request_id, out.stopped,
                    ",".join(f"{label}={o}" for label, o in out.results))
        return out

    async def _process(self, req: LifecycleRequest, out: Outcome) -> None:
        client = self._catalog.for_client(req.client_id)
        if client is None:
            out.stopped = True
            plan = Plan(kind=req.kind, problems=["This client is not in the agent's catalogue."])
            out.plan = plan
            await self._note(out, req.ticket_id, stopped_note(plan, req.request_id))
            return

        fields = await self._extractor.extract(req, client, run_label=out.run_label)
        plan = build_plan(fields, client, today=self._today())
        out.plan = plan
        if not plan.runnable:
            out.stopped = True
            await self._note(out, req.ticket_id, stopped_note(plan, req.request_id))
            return

        await self._note(out, req.ticket_id, plan_note(plan))
        skip = False
        for step in plan.steps:
            if skip:
                out.results.append((step.label, "skipped"))
                continue
            result = await self._run(step, plan, out)
            out.results.append((step.label if result != "stopped" else self._why(step, plan), result))
            if result != "done" and step.stop_on_fail:
                skip = True
        await self._note(out, req.ticket_id, outcome_note(plan, out.results, req.request_id))

    @staticmethod
    def _why(step: Step, plan: Plan) -> str:
        if plan.kind == "joiner":
            return f"{step.label}: {plan.upn} already exists, so no new account was made"
        return f"{step.label}: no account {plan.upn} was found"

    async def _run(self, step: Step, plan: Plan, out: Outcome) -> str:
        try:
            result = await self._mcp.call(step.tool, step.args, run_label=out.run_label)
        except GovernanceRefused as exc:
            if not exc.after_review:
                return "refused"
            return "timed_out" if exc.resolution == "timed_out" else "rejected"
        except OutcomeUnknown:
            # The connection closed while the step was held for approval. It may
            # still be approved and run, so it is neither done nor failed.
            logger.warning("request %s: step %s outcome unknown", out.request_id, step.tool)
            return "unknown"
        except (ToolFailed, GatewayError):
            logger.warning("request %s: step %s failed", out.request_id, step.tool)
            return "failed"
        if step.kind == "check":
            exists = _user_exists(result.data)
            expected = plan.kind == "leaver"
            return "done" if exists == expected else "stopped"
        return "done"
