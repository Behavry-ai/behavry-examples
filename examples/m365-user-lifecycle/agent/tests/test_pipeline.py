import asyncio
from datetime import date

from helpers import CATALOG, joiner_fields, joiner_request, leaver_fields, leaver_request

from m365_lifecycle.app import Worker
from m365_lifecycle.behavry_mcp import JSONRPC_ESCALATED, JSONRPC_FORBIDDEN, GovernanceRefused, ToolResult
from m365_lifecycle.config import Settings
from m365_lifecycle.pipeline import Pipeline

S = Settings(behavry_proxy_url="https://plane.example", behavry_client_id="c", behavry_client_secret="s",
             anthropic_api_key="sk-ant-x", webhook_secret="w", client_catalog_path="x", halo_note_actiontype_id=9)


class FakeMCP:
    def __init__(self, existing=(), outcomes=None):
        self.calls, self.existing, self.outcomes = [], set(existing), outcomes or {}

    async def call(self, key, args, *, run_label):
        self.calls.append((key, args, run_label))
        if key in self.outcomes:
            raise self.outcomes[key]
        if key == "get_user":
            found = args["upn"] in self.existing
            return ToolResult("", {"id": "u1", "userPrincipalName": args["upn"]} if found else {"found": False})
        return ToolResult("", {"ok": True})

    def keys(self):
        return [c[0] for c in self.calls]

    def notes(self):
        return [c[1]["note"] for c in self.calls if c[0] == "ticket_note"]


class FakeExtractor:
    def __init__(self, fields):
        self.fields, self.calls = fields, 0

    async def extract(self, req, client, *, run_label):
        self.calls += 1
        return self.fields


def run(mcp, fields, req):
    p = Pipeline(S, mcp, FakeExtractor(fields), CATALOG, today=lambda: date(2026, 10, 14))
    return asyncio.run(p.process(req))


def test_joiner_happy_path_notes_plan_then_outcome():
    mcp = FakeMCP()
    out = run(mcp, joiner_fields(), joiner_request())
    assert mcp.keys() == ["ticket_note", "get_user", "create_user", "assign_license",
                          "add_group_member", "add_group_member", "ticket_note"]
    assert all(o == "done" for _, o in out.results)
    plan, outcome = mcp.notes()
    assert "riley.chen@acmeclinic.example" in plan and "wait for a person" in plan
    assert "Temporary Access Pass" in outcome
    assert all("password" not in n.lower() for n in mcp.notes())
    assert {c[2] for c in mcp.calls} == {"joiner-REQ-1001"}
    note_args = [c[1] for c in mcp.calls if c[0] == "ticket_note"][0]
    assert note_args["send_email"] is False and note_args["actiontype_id"] == 9


def test_joiner_rejected_creation_skips_the_rest_and_never_retries():
    mcp = FakeMCP(outcomes={"create_user": GovernanceRefused(JSONRPC_ESCALATED, "denied", "denied")})
    out = run(mcp, joiner_fields(), joiner_request())
    assert mcp.keys().count("create_user") == 1
    assert "assign_license" not in mcp.keys()
    assert [o for _, o in out.results] == ["done", "rejected", "skipped", "skipped", "skipped"]
    assert "rejected it in Behavry" in mcp.notes()[-1]


def test_existing_account_stops_before_creation():
    mcp = FakeMCP(existing={"riley.chen@acmeclinic.example"})
    out = run(mcp, joiner_fields(), joiner_request())
    assert "create_user" not in mcp.keys()
    assert "already exists" in out.results[0][0]


def test_leaver_containment_runs_even_when_wind_down_is_held_then_times_out():
    mcp = FakeMCP(existing={"jordan.lee@acmeclinic.example"},
                  outcomes={"convert_mailbox_to_shared": GovernanceRefused(JSONRPC_ESCALATED, "t", "timed_out"),
                            "remove_licenses": GovernanceRefused(JSONRPC_FORBIDDEN, "no")})
    out = run(mcp, leaver_fields(), leaver_request())
    assert [o for _, o in out.results] == ["done", "done", "done", "timed_out", "refused"]
    assert "no one approved it in time" in mcp.notes()[-1]


def test_unknown_leaver_account_stops():
    mcp = FakeMCP()
    out = run(mcp, leaver_fields(), leaver_request())
    assert "disable_user" not in mcp.keys() and "no account" in out.results[0][0]


def test_stopped_request_writes_why_and_changes_nothing():
    mcp = FakeMCP()
    out = run(mcp, joiner_fields(suspicious_content=True, suspicious_reason="asks for admin"), joiner_request())
    assert out.stopped and mcp.keys() == ["ticket_note"]
    assert "Nothing was changed" in mcp.notes()[0]


def test_unknown_client_stops_without_a_model_call():
    mcp, ex = FakeMCP(), FakeExtractor(joiner_fields())
    p = Pipeline(S, mcp, ex, CATALOG)
    out = asyncio.run(p.process(joiner_request(client_id=99)))
    assert out.stopped and ex.calls == 0


def test_worker_drops_repeat_deliveries():
    async def go():
        w = Worker(pipeline=None)
        assert w.accept(joiner_request())
        assert not w.accept(joiner_request())
        assert w.queue.qsize() == 1
    asyncio.run(go())


def test_held_step_cut_off_is_unknown_and_skips_dependents():
    from m365_lifecycle.behavry_mcp import OutcomeUnknown

    mcp = FakeMCP(outcomes={"create_user": OutcomeUnknown("tools/call: HTTP 504 before Behavry answered")})
    out = run(mcp, joiner_fields(), joiner_request())
    assert [o for _, o in out.results] == ["done", "unknown", "skipped", "skipped", "skipped"]
    assert "approval queue" in mcp.notes()[-1]


class RefuseNotesOnce(FakeMCP):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.refused = False

    async def call(self, key, args, *, run_label):
        if key == "ticket_note" and not self.refused:
            self.refused = True
            self.calls.append((key, args, run_label))
            raise GovernanceRefused(JSONRPC_FORBIDDEN, "Request blocked: potential prompt injection detected")
        return await super().call(key, args, run_label=run_label)


def test_refused_note_is_replaced_by_one_without_form_text():
    mcp = RefuseNotesOnce()
    run(mcp, joiner_fields(suspicious_content=True, suspicious_reason="IMPORTANT SYSTEM NOTE"), joiner_request())
    notes = mcp.notes()
    assert len(notes) == 2 and "IMPORTANT SYSTEM NOTE" not in notes[1]
    assert "Behavry blocked the agent" in notes[1]
