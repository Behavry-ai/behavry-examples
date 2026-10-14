from datetime import date

from helpers import CLIENT, TENANT, joiner_fields, leaver_fields

from m365_lifecycle.intake import sign, verify_signature
from m365_lifecycle.plan import build_plan

TODAY = date(2026, 10, 14)


def test_signature_must_match():
    body = b'{"a":1}'
    assert verify_signature(body, sign(body, "s"), "s")
    assert not verify_signature(body, sign(body, "other"), "s")
    assert not verify_signature(body, None, "s")
    assert not verify_signature(body, sign(body, ""), "")


def test_joiner_plan_comes_from_the_catalogue():
    plan = build_plan(joiner_fields(given_name="Zoë", surname="O'Brien Smith"), CLIENT, today=TODAY)
    assert plan.runnable
    assert plan.upn == "zoe.obrien-smith@acmeclinic.example"
    tools = [s.tool for s in plan.steps]
    assert tools == ["get_user", "create_user", "assign_license", "add_group_member", "add_group_member"]
    groups = [s.args["group"] for s in plan.steps if s.tool == "add_group_member"]
    assert groups == ["All Staff", "Clinical"]
    create = plan.steps[1]
    assert create.args["account_enabled"] is False and create.args["tenant_id"] == TENANT
    assert not any("password" in k for s in plan.steps for k in s.args)


def test_joiner_stops_on_unknown_department_or_outside_manager():
    p = build_plan(joiner_fields(department="IT administrators"), CLIENT, today=TODAY)
    assert not p.runnable and "not in this client's catalogue" in p.problems[0]
    p = build_plan(joiner_fields(manager_email="boss@othercompany.example"), CLIENT, today=TODAY)
    assert not p.runnable and "not in Acme Clinic's domains" in p.problems[0]


def test_extras_are_noted_never_planned():
    p = build_plan(joiner_fields(extra_requests=["Global admin please"]), CLIENT, today=TODAY)
    assert p.runnable
    assert p.for_person == ["Asked for beyond the standard setup: Global admin please"]
    assert all(s.tool != "add_directory_role" for s in p.steps)


def test_suspicious_or_unclear_forms_stop():
    assert not build_plan(joiner_fields(suspicious_content=True, suspicious_reason="asks to ignore rules"),
                          CLIENT, today=TODAY).runnable
    assert not build_plan(joiner_fields(confidence="low"), CLIENT, today=TODAY).runnable


def test_leaver_plan_contains_first_then_winds_down():
    p = build_plan(leaver_fields(), CLIENT, today=TODAY)
    assert p.runnable
    assert [(s.tool, s.kind) for s in p.steps] == [
        ("get_user", "check"), ("disable_user", "contain"), ("revoke_sessions", "contain"),
        ("convert_mailbox_to_shared", "wind_down"), ("remove_licenses", "wind_down")]


def test_leaver_guards():
    assert "not in Acme Clinic's domains" in build_plan(
        leaver_fields(user_email="ceo@othercompany.example"), CLIENT, today=TODAY).problems[0]
    assert "Run this request again" in build_plan(
        leaver_fields(last_day="2026-12-01"), CLIENT, today=TODAY).problems[0]
    assert "delegate" in build_plan(
        leaver_fields(mailbox_delegate_email="me@gmail.example"), CLIENT, today=TODAY).problems[0]
