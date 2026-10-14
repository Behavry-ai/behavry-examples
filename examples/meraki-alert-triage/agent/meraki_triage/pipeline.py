"""One alert, start to finish.

1. Look the device up in Halo: asset, client, site, any open ticket for it.
2. Triage with the model (skipped for a recovery, which needs no judgement).
3. Write the note: onto the open ticket, or onto a new one.
4. Business escalation: when a person is needed, assign the on-call tech.
5. Governance escalation (week 2, off by default): ask Behavry to run a
   remediation. Policy holds it for a person; a rejection or a timeout is
   recorded on the ticket and never retried.

Every call carries the alert's run label. Halo response shapes are read
defensively, because they differ between Halo versions and between Halo
direct and Halo behind a gateway; adjust ``_records`` if yours differ.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from meraki_triage.alerts import MerakiAlert, instruction_like_fields
from meraki_triage.behavry_mcp import BehavryMCP, GatewayError, GovernanceRefused, ToolFailed
from meraki_triage.config import Settings
from meraki_triage.notes import (
    PRIORITY_BY_SEVERITY,
    recovery_note,
    remediation_outcome_note,
    remediation_requested_note,
    ticket_summary,
    triage_note,
)
from meraki_triage.triage import Triage, TriageContext, Triager

logger = logging.getLogger(__name__)

# Logical tool keys (see config.ToolNames).
REQUIRED_TOOLS = ("search_assets", "list_tickets_by_client", "create_ticket", "update_ticket", "add_action")


@dataclass
class Outcome:
    """What happened for one alert, for logs and tests."""

    alert_id: str
    run_label: str
    ticket_id: int | None = None
    created_ticket: bool = False
    triage: Triage | None = None
    assigned_to_human: bool = False
    remediation: str | None = None  # approved, rejected, timed_out, refused, failed
    steps: list[str] = field(default_factory=list)


def run_label_for(alert: MerakiAlert) -> str:
    # Printable ASCII, no spaces, at most 128 characters (Behavry's rule).
    safe = "".join(c for c in alert.stable_id if c.isalnum() or c in "-_.")
    return f"meraki-{safe}"[:128]


def _records(data: Any, key: str) -> list[dict[str, Any]]:
    """Halo list endpoints answer ``{"<key>": [...]}``, a bare list, or one record."""
    if isinstance(data, dict):
        inner = data.get(key)
        if isinstance(inner, list):
            return [r for r in inner if isinstance(r, dict)]
        return [data] if "id" in data else []
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    return []


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


class Pipeline:
    def __init__(self, settings: Settings, mcp: BehavryMCP, triager: Triager) -> None:
        self._s = settings
        self._mcp = mcp
        self._triager = triager

    async def _call(self, out: Outcome, key: str, args: dict[str, Any]) -> Any:
        out.steps.append(key)
        result = await self._mcp.call(key, args, run_label=out.run_label)
        return result.data

    async def _note(self, out: Outcome, ticket_id: int, body: str) -> None:
        args: dict[str, Any] = {"ticket_id": ticket_id, "note": body, "send_email": False}
        if self._s.halo_note_actiontype_id is not None:
            args["actiontype_id"] = self._s.halo_note_actiontype_id
        await self._call(out, "add_action", args)

    # -- lookup -------------------------------------------------------------

    async def _lookup(
        self, out: Outcome, alert: MerakiAlert,
    ) -> tuple[TriageContext, int | None, int | None, int | None]:
        notes: list[str] = []
        asset: dict[str, Any] | None = None
        for term in (alert.device_serial, alert.device_mac, alert.device_name):
            if not term:
                continue
            try:
                found = _records(await self._call(out, "search_assets", {"search": term}), "assets")
            except (ToolFailed, GovernanceRefused) as exc:
                notes.append(f"asset search for {term!r} failed: {exc}")
                continue
            if found:
                asset = found[0]
                break
        if asset is None:
            notes.append("no matching asset in Halo")

        client_id = _int_or_none(asset.get("client_id")) if asset else None
        site_id = _int_or_none(asset.get("site_id")) if asset else None
        if self._s.halo_sandbox_client_id is not None:
            client_id = self._s.halo_sandbox_client_id
            site_id = None

        open_ticket: dict[str, Any] | None = None
        if client_id is not None and alert.device_serial:
            try:
                tickets = _records(await self._call(
                    out, "list_tickets_by_client", {"client_id": client_id, "open_only": True},
                ), "tickets")
                open_ticket = next(
                    (t for t in tickets if alert.device_serial in str(t.get("summary", ""))), None,
                )
            except (ToolFailed, GovernanceRefused) as exc:
                notes.append(f"open ticket lookup failed: {exc}")

        ctx = TriageContext(
            client_name=(asset or {}).get("client_name"),
            site_name=(asset or {}).get("site_name"),
            asset_summary=(
                f"{asset.get('inventory_number') or asset.get('key_field') or asset.get('id')}"
                f" ({asset.get('assettype_name', 'asset')})"
            ) if asset else None,
            open_ticket_summary=(
                f"#{open_ticket.get('id')}: {open_ticket.get('summary')}" if open_ticket else None
            ),
            lookup_notes=notes,
        )
        ticket_id = _int_or_none(open_ticket.get("id")) if open_ticket else None
        return ctx, client_id, site_id, ticket_id

    # -- the run ------------------------------------------------------------

    async def process(self, alert: MerakiAlert) -> Outcome:
        out = Outcome(alert_id=alert.stable_id, run_label=run_label_for(alert))
        try:
            await self._process(alert, out)
        except GatewayError:
            logger.exception("alert %s: Behavry gateway error", out.alert_id)
            out.steps.append("gateway_error")
        logger.info(
            "alert %s done: ticket=%s created=%s human=%s remediation=%s steps=%s",
            out.alert_id, out.ticket_id, out.created_ticket, out.assigned_to_human,
            out.remediation, ",".join(out.steps),
        )
        return out

    async def _process(self, alert: MerakiAlert, out: Outcome) -> None:
        ctx, client_id, site_id, ticket_id = await self._lookup(out, alert)
        out.ticket_id = ticket_id

        if alert.kind.is_up:
            # A recovery after the hold: say so on the outage's ticket, if any.
            if ticket_id is not None:
                await self._note(out, ticket_id, recovery_note(alert))
            return

        flagged = instruction_like_fields(alert)
        triage = await self._triager.triage(alert, ctx, run_label=out.run_label)
        if flagged and not triage.suspicious_content:
            triage = triage.model_copy(update={
                "suspicious_content": True,
                "suspicious_reason": f"instruction-like text in {', '.join(flagged)}",
            })
        out.triage = triage
        note = triage_note(alert, triage, flagged_fields=flagged)

        if ticket_id is None:
            args: dict[str, Any] = {
                "summary": ticket_summary(alert, triage),
                "details": note,
                "priority_id": PRIORITY_BY_SEVERITY[triage.severity],
            }
            if client_id is not None:
                args["client_id"] = client_id
            if site_id is not None:
                args["site_id"] = site_id
            if self._s.halo_ticket_type_id is not None:
                args["tickettype_id"] = self._s.halo_ticket_type_id
            created = _records(await self._call(out, "create_ticket", args), "tickets")
            ticket_id = _int_or_none(created[0].get("id")) if created else None
            out.ticket_id, out.created_ticket = ticket_id, True
            if ticket_id is None:
                logger.warning("alert %s: ticket created but no id came back", out.alert_id)
                return
        else:
            await self._note(out, ticket_id, note)

        needs_human = triage.needs_human or triage.confidence == "low" or triage.suspicious_content
        if needs_human and (self._s.halo_oncall_agent_id or self._s.halo_oncall_team):
            update: dict[str, Any] = {"id": ticket_id}
            if self._s.halo_oncall_agent_id is not None:
                update["agent_id"] = self._s.halo_oncall_agent_id
            if self._s.halo_oncall_team:
                update["team"] = self._s.halo_oncall_team
            await self._call(out, "update_ticket", update)
            out.assigned_to_human = True

        if self._wants_remediation(triage):
            await self._request_reboot(out, alert, ticket_id)

    def _wants_remediation(self, triage: Triage) -> bool:
        return (
            self._s.allow_remediation_requests
            and self._mcp.has("reboot_device")
            and triage.recommended_action == "reboot_device"
            and triage.confidence != "low"
            and not triage.suspicious_content
        )

    async def _request_reboot(self, out: Outcome, alert: MerakiAlert, ticket_id: int) -> None:
        action = "Reboot"
        await self._note(out, ticket_id, remediation_requested_note(action, alert))
        try:
            await self._call(out, "reboot_device", {"serial": alert.device_serial})
        except GovernanceRefused as exc:
            if not exc.after_review:
                out.remediation = "refused"
                text = "Not carried out: policy does not allow this action."
            elif exc.resolution == "timed_out":
                out.remediation = "timed_out"
                text = "Not carried out: no one approved it in time. A technician should decide."
            else:
                out.remediation = "rejected"
                text = "Not carried out: a reviewer rejected it in Behavry."
            await self._note(out, ticket_id, remediation_outcome_note(action, text))
            return
        except (ToolFailed, GatewayError) as exc:
            out.remediation = "failed"
            await self._note(out, ticket_id, remediation_outcome_note(
                action, f"Approved, but the device did not accept it: {exc}",
            ))
            return
        out.remediation = "approved"
        await self._note(out, ticket_id, remediation_outcome_note(
            action, "Approved in Behavry and sent to the device. Check it comes back up.",
        ))
