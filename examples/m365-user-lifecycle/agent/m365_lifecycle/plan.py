"""Turn the form's fields into a plan, using only the MSP's catalogue.

The plan is where the agent's judgement is replaced by the MSP's own rules:

* the user name is built from the catalogue's domain, never taken from the form;
* the licence and groups come from the catalogue for the department, and a
  department that is not in the catalogue stops the request;
* every address the agent touches must be in the client's own domains, so a
  request can never reach into another client's tenant;
* a leaver is not processed before their last day;
* low confidence or a suspicious form stops the request before any step runs.

Problems stop the whole request and go to a person. ``for_person`` items are
noted on the ticket but do not stop the standard steps.

Step kinds tell the reader (and the policy author) what each step is:
``check`` reads, ``contain`` cuts access (allowed by policy so a leaver is
locked out at once), ``grant`` gives access (account creation is held for a
person), ``wind_down`` changes mailbox and licences (held for a person).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

from m365_lifecycle.extract import Fields, JoinerFields, LeaverFields
from m365_lifecycle.intake import ClientEntry

StepKind = Literal["check", "contain", "grant", "wind_down"]


@dataclass(frozen=True)
class Step:
    tool: str  # logical tool key, see config.ToolNames
    args: dict[str, Any]
    label: str
    kind: StepKind
    # When this step does not complete, skip every later step.
    stop_on_fail: bool = False


@dataclass
class Plan:
    kind: Literal["joiner", "leaver"]
    upn: str | None = None
    steps: list[Step] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    for_person: list[str] = field(default_factory=list)

    @property
    def runnable(self) -> bool:
        return not self.problems and bool(self.steps)


_EMAIL = re.compile(r"^[^@\s]+@([^@\s]+)$")


def _domain(email: str) -> str | None:
    m = _EMAIL.match(email.strip().lower())
    return m.group(1) if m else None


def _in_client(email: str, client: ClientEntry) -> bool:
    return _domain(email) in {d.lower() for d in client.domains}


def _slug(name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9-]", "", ascii_name.lower().replace(" ", "-")).strip("-")


def _date(value: str) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _common_checks(fields: Fields, plan: Plan) -> None:
    if fields.suspicious_content:
        plan.problems.append(
            "The form reads like an attempt to instruct the agent or to get unusual access"
            + (f": {fields.suspicious_reason}" if fields.suspicious_reason else ".")
        )
    if fields.confidence == "low":
        plan.problems.append("The form is unclear, so nothing was changed.")
    for extra in fields.extra_requests:
        plan.for_person.append(f"Asked for beyond the standard setup: {extra}")


def plan_joiner(fields: JoinerFields, client: ClientEntry) -> Plan:
    plan = Plan(kind="joiner")
    _common_checks(fields, plan)

    given, surname = _slug(fields.given_name), _slug(fields.surname)
    if not given or not surname:
        plan.problems.append("The new starter's first and last name are needed.")
        return plan
    plan.upn = f"{given}.{surname}@{client.domains[0].lower()}"

    dept = next((d for d in client.departments if d.lower() == fields.department.strip().lower()), None)
    if dept is None:
        plan.problems.append(
            f"Department {fields.department!r} is not in this client's catalogue, so the agent "
            "cannot tell which groups apply."
        )
    manager = fields.manager_email.strip().lower()
    if manager and not _in_client(manager, client):
        plan.problems.append(f"The manager {manager} is not in {client.name}'s domains.")
    if plan.problems:
        return plan

    t = client.tenant_id
    plan.steps = [
        Step("get_user", {"tenant_id": t, "upn": plan.upn}, "Check the name is free", "check", stop_on_fail=True),
        Step("create_user", {
            "tenant_id": t, "upn": plan.upn,
            "display_name": f"{fields.given_name.strip()} {fields.surname.strip()}",
            "given_name": fields.given_name.strip(), "surname": fields.surname.strip(),
            "department": dept, "job_title": fields.job_title.strip(),
            "manager_upn": manager or None, "usage_location": client.usage_location,
            # Created disabled; a technician enables it and issues a Temporary
            # Access Pass on the start date.
            "account_enabled": False,
        }, "Create the account (sign-in off until the start date)", "grant", stop_on_fail=True),
        Step("assign_license", {"tenant_id": t, "upn": plan.upn, "sku": client.license_sku},
             f"Assign {client.license_sku}", "grant"),
    ]
    for group in [*client.baseline_groups, *client.departments[dept]]:
        plan.steps.append(Step("add_group_member", {"tenant_id": t, "upn": plan.upn, "group": group},
                               f"Add to {group}", "grant"))
    return plan


def plan_leaver(fields: LeaverFields, client: ClientEntry, *, today: date) -> Plan:
    plan = Plan(kind="leaver")
    _common_checks(fields, plan)

    upn = fields.user_email.strip().lower()
    if not upn or not _in_client(upn, client):
        plan.problems.append(f"The leaver's address {upn or '(none)'} is not in {client.name}'s domains.")
        return plan
    plan.upn = upn
    last_day = _date(fields.last_day)
    if last_day and last_day > today:
        plan.problems.append(f"The last day is {last_day.isoformat()}. Run this request again on or after it.")
    delegate = fields.mailbox_delegate_email.strip().lower()
    if delegate and not _in_client(delegate, client):
        plan.problems.append(f"The mailbox delegate {delegate} is not in {client.name}'s domains.")
    if plan.problems:
        return plan

    t = client.tenant_id
    plan.steps = [
        Step("get_user", {"tenant_id": t, "upn": upn}, "Find the account", "check", stop_on_fail=True),
        Step("disable_user", {"tenant_id": t, "upn": upn}, "Block sign-in", "contain"),
        Step("revoke_sessions", {"tenant_id": t, "upn": upn}, "End every signed-in session", "contain"),
        Step("convert_mailbox_to_shared", {"tenant_id": t, "upn": upn, "delegate_upn": delegate or None},
             "Convert the mailbox to shared" + (f" for {delegate}" if delegate else ""), "wind_down"),
        Step("remove_licenses", {"tenant_id": t, "upn": upn}, "Remove licences", "wind_down"),
    ]
    return plan


def build_plan(fields: Fields, client: ClientEntry, *, today: date) -> Plan:
    if isinstance(fields, JoinerFields):
        return plan_joiner(fields, client)
    return plan_leaver(fields, client, today=today)
