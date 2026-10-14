from __future__ import annotations

from pathlib import Path
from typing import Any

from m365_lifecycle.extract import JoinerFields, LeaverFields
from m365_lifecycle.intake import Catalog, LifecycleRequest

CATALOG = Catalog.load(Path(__file__).resolve().parent.parent / "catalog.example.json")
CLIENT = CATALOG.for_client(40)
TENANT = "00000000-0000-4000-8000-00000000ac01"


def joiner_request(**kw: Any) -> LifecycleRequest:
    base = {"request_id": "REQ-1001", "ticket_id": 7001, "client_id": 40, "kind": "joiner",
            "form": "New starter: Riley Chen, Clinical, Nurse, starts 2026-11-02, "
                    "manager sam.rivera@acmeclinic.example"}
    base.update(kw)
    return LifecycleRequest.model_validate(base)


def leaver_request(**kw: Any) -> LifecycleRequest:
    base = {"request_id": "REQ-2001", "ticket_id": 7002, "client_id": 40, "kind": "leaver",
            "form": "Jordan Lee (jordan.lee@acmeclinic.example) leaves 2026-10-10. Give Sam the mailbox."}
    base.update(kw)
    return LifecycleRequest.model_validate(base)


def joiner_fields(**kw: Any) -> JoinerFields:
    base = dict(given_name="Riley", surname="Chen", department="Clinical", job_title="Nurse",
                manager_email="sam.rivera@acmeclinic.example", start_date="2026-11-02", extra_requests=[],
                suspicious_content=False, suspicious_reason="", confidence="high")
    base.update(kw)
    return JoinerFields(**base)


def leaver_fields(**kw: Any) -> LeaverFields:
    base = dict(user_email="jordan.lee@acmeclinic.example", last_day="2026-10-10",
                mailbox_delegate_email="sam.rivera@acmeclinic.example", extra_requests=[],
                suspicious_content=False, suspicious_reason="", confidence="high")
    base.update(kw)
    return LeaverFields(**base)
