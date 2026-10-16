import asyncio
import json

import httpx
import pytest

from meraki_triage.behavry_mcp import (
    BehavryMCP,
    GatewayError,
    GovernanceRefused,
    ToolFailed,
)

TOOLS = [
    {"name": "sj-1__halo_add_action"},
    {"name": "sj-2__halo_add_action"},
    {"name": "sj-1__halo_search_assets"},
]


def client(handler) -> BehavryMCP:
    return BehavryMCP("https://plane.example", "cid", "csecret", transport=httpx.MockTransport(handler))


def ok(req_id, result):
    return httpx.Response(200, json={"jsonrpc": "2.0", "id": req_id, "result": result})


def err(req_id, code, message, data=None):
    error = {"code": code, "message": message}
    if data:
        error["data"] = data
    return httpx.Response(200, json={"jsonrpc": "2.0", "id": req_id, "error": error})


def test_resolves_namespaced_tools_and_pins_server_id():
    def handler(request):
        body = json.loads(request.content)
        assert str(request.url) == "https://plane.example/mcp/v1"
        assert request.headers["Authorization"].startswith("Basic ")
        return ok(body["id"], {"tools": TOOLS})

    async def go():
        mcp = client(handler)
        missing = await mcp.resolve_tools(
            {"add_action": "halo_add_action", "create_ticket": "halo_create_ticket"}, server_id="sj-2"
        )
        assert missing == {"create_ticket": "halo_create_ticket"}
        assert mcp._names["add_action"] == "sj-2__halo_add_action"

        loose = client(handler)
        assert await loose.resolve_tools({"add_action": "halo_add_action"}) == {}
        assert loose._names["add_action"] == "sj-1__halo_add_action"

    asyncio.run(go())


def _resolved(handler) -> BehavryMCP:
    mcp = client(handler)
    mcp._names["add_action"] = "sj-1__halo_add_action"
    return mcp


def test_call_sends_run_label_and_parses_json_result():
    seen = {}

    def handler(request):
        body = json.loads(request.content)
        seen["label"] = request.headers.get("X-Behavry-Run-Id")
        seen["params"] = body["params"]
        return ok(body["id"], {"content": [{"type": "text", "text": '{"id": 42}'}]})

    async def go():
        result = await _resolved(handler).call("add_action", {"ticket_id": 1}, run_label="meraki-1")
        assert result.data == {"id": 42}

    asyncio.run(go())
    assert seen["label"] == "meraki-1"
    assert seen["params"] == {"name": "sj-1__halo_add_action", "arguments": {"ticket_id": 1}}


def test_tool_error_result_raises_tool_failed():
    def handler(request):
        body = json.loads(request.content)
        return ok(body["id"], {"isError": True, "content": [{"type": "text", "text": "Halo 400"}]})

    with pytest.raises(ToolFailed, match="Halo 400"):
        asyncio.run(_resolved(handler).call("add_action", {}, run_label="x"))


@pytest.mark.parametrize(
    ("code", "data", "after_review", "resolution"),
    [
        (-32003, None, False, None),
        (-32004, {"resolution": "denied"}, True, "denied"),
        (-32004, {"resolution": "timed_out"}, True, "timed_out"),
    ],
)
def test_governance_outcomes(code, data, after_review, resolution):
    def handler(request):
        return err(json.loads(request.content)["id"], code, "nope", data)

    with pytest.raises(GovernanceRefused) as info:
        asyncio.run(_resolved(handler).call("add_action", {}, run_label="x"))
    assert info.value.after_review is after_review
    assert info.value.resolution == resolution


def test_sse_response_is_decoded():
    def handler(request):
        req_id = json.loads(request.content)["id"]
        msg = json.dumps({"jsonrpc": "2.0", "id": req_id, "result": {"content": [{"type": "text", "text": "done"}]}})
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              text=f"event: message\ndata: {msg}\n\n")

    result = asyncio.run(_resolved(handler).call("add_action", {}, run_label="x"))
    assert result.text == "done" and result.data is None


def test_bad_credentials_and_unresolved_tools_are_gateway_errors():
    with pytest.raises(GatewayError, match="401"):
        asyncio.run(_resolved(lambda r: httpx.Response(401)).call("add_action", {}, run_label="x"))
    with pytest.raises(GatewayError, match="not resolved"):
        asyncio.run(client(lambda r: httpx.Response(200)).call("create_ticket", {}, run_label="x"))


def test_gateway_timeout_on_a_call_is_outcome_unknown():
    from meraki_triage.behavry_mcp import OutcomeUnknown

    with pytest.raises(OutcomeUnknown):
        asyncio.run(_resolved(lambda r: httpx.Response(504)).call("add_action", {}, run_label="x"))
