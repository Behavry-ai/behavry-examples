"""A small client for Behavry's MCP gateway (``POST {plane}/mcp/v1``).

Every tool call the agent makes goes through here, so each one is bound to the
agent's identity, checked against the tenant's policy, and written to the
signed record before it reaches the Microsoft 365 or PSA tools. Three things
matter to this agent:

* **Auth that never expires.** Client credentials go as HTTP Basic; Behavry
  exchanges them per request.
* **One label per request.** ``X-Behavry-Run-Id`` groups every call made for a
  joiner or leaver request, model calls included, into one Decision Trace.
* **Held calls take a while.** When policy says a call needs approval, Behavry
  holds the request open until a person decides or the hold times out (up to
  30 minutes, by the agent's risk tier). The read timeout is set above that.
  A load balancer in front of Behavry may still close the connection sooner
  (a 504): that is ``OutcomeUnknown``, because the request can still be
  approved and executed after the agent stops waiting.
"""
from __future__ import annotations

import base64
import itertools
import json
from dataclasses import dataclass
from typing import Any

import httpx

# Behavry's JSON-RPC error codes for a governance outcome.
JSONRPC_FORBIDDEN = -32003
JSONRPC_ESCALATED = -32004

RUN_ID_HEADER = "X-Behavry-Run-Id"
NS_SEP = "__"

# 30-minute maximum hold plus a minute of margin.
DEFAULT_READ_TIMEOUT = 31 * 60


class GatewayError(RuntimeError):
    """Transport or protocol failure talking to Behavry."""


class GovernanceRefused(RuntimeError):
    """Behavry did not let the call through.

    ``after_review`` is True when the call was held for a person and then
    rejected or timed out, False when policy refused it outright.
    """

    def __init__(self, code: int, message: str, resolution: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.after_review = code == JSONRPC_ESCALATED
        # "denied" or "timed_out" for a held call; None otherwise.
        self.resolution = resolution


class OutcomeUnknown(GatewayError):
    """The connection ended before Behavry answered, typically a load balancer
    timeout while the call was held for approval. The request may still be
    approved and executed: never treat this as a failure, and never retry."""


class ToolFailed(RuntimeError):
    """The call was allowed, and the downstream tool reported an error."""


@dataclass(frozen=True)
class ToolResult:
    text: str
    data: Any  # parsed JSON when the tool returned JSON text, else None


def basic_auth(client_id: str, client_secret: str) -> str:
    return "Basic " + base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()


class BehavryMCP:
    def __init__(
        self,
        proxy_url: str,
        client_id: str,
        client_secret: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        read_timeout: float = DEFAULT_READ_TIMEOUT,
    ) -> None:
        base = proxy_url.rstrip("/")
        self._url = base if base.endswith("/mcp/v1") else f"{base}/mcp/v1"
        self._http = httpx.AsyncClient(
            transport=transport,
            timeout=httpx.Timeout(30.0, read=read_timeout),
            headers={
                "Authorization": basic_auth(client_id, client_secret),
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
        )
        self._ids = itertools.count(1)
        self._names: dict[str, str] = {}

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _rpc(self, method: str, params: dict[str, Any] | None, run_label: str | None) -> Any:
        req_id = next(self._ids)
        body = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}}
        headers = {RUN_ID_HEADER: run_label} if run_label else {}
        try:
            resp = await self._http.post(self._url, json=body, headers=headers)
        except httpx.TimeoutException as exc:
            raise OutcomeUnknown(f"{method}: no answer before the connection timed out") from exc
        except httpx.HTTPError as exc:
            raise GatewayError(f"{method}: {type(exc).__name__}: {exc}") from exc
        if resp.status_code in (502, 503, 504) and method == "tools/call":
            raise OutcomeUnknown(f"{method}: HTTP {resp.status_code} before Behavry answered")
        if resp.status_code == 401:
            raise GatewayError("Behavry rejected the agent credentials (401)")
        if resp.status_code >= 400:
            raise GatewayError(f"{method}: HTTP {resp.status_code}")

        message = _decode(resp, req_id)
        if "error" in message and message["error"]:
            err = message["error"]
            code = int(err.get("code", 0))
            text = str(err.get("message", "unknown error"))
            if code in (JSONRPC_FORBIDDEN, JSONRPC_ESCALATED):
                data = err.get("data") if isinstance(err.get("data"), dict) else {}
                raise GovernanceRefused(code, text, data.get("resolution"))
            raise GatewayError(f"{method}: {code} {text}")
        return message.get("result")

    async def resolve_tools(self, logical: dict[str, str], *, server_id: str = "") -> dict[str, str]:
        """Map each logical name to the gateway's namespaced tool name.

        Returns the logical names that could not be found, mapped to what was
        looked for; an empty dict means everything resolved.
        """
        result = await self._rpc("tools/list", {}, None)
        available = [t.get("name", "") for t in (result or {}).get("tools", [])]
        missing: dict[str, str] = {}
        for key, wanted in logical.items():
            if server_id:
                exact = f"{server_id}{NS_SEP}{wanted}"
                match = exact if exact in available else None
            else:
                match = next((n for n in available if n.endswith(f"{NS_SEP}{wanted}")), None)
            if match:
                self._names[key] = match
            else:
                missing[key] = wanted
        return missing

    def has(self, key: str) -> bool:
        return key in self._names

    async def call(self, key: str, arguments: dict[str, Any], *, run_label: str) -> ToolResult:
        name = self._names.get(key)
        if name is None:
            raise GatewayError(f"tool {key!r} was not resolved from the gateway catalogue")
        result = await self._rpc(
            "tools/call", {"name": name, "arguments": arguments}, run_label
        ) or {}
        text = "\n".join(
            c.get("text", "") for c in result.get("content", []) if c.get("type") == "text"
        )
        if result.get("isError"):
            raise ToolFailed(text or f"{key} failed")
        try:
            data = json.loads(text) if text else None
        except json.JSONDecodeError:
            data = None
        return ToolResult(text=text, data=data)


def _decode(resp: httpx.Response, req_id: int) -> dict[str, Any]:
    """A JSON-RPC message from a plain JSON or an SSE response."""
    ctype = resp.headers.get("content-type", "")
    if "text/event-stream" not in ctype:
        try:
            return resp.json()
        except ValueError as exc:
            raise GatewayError("gateway returned a non-JSON response") from exc
    last: dict[str, Any] | None = None
    for line in resp.text.splitlines():
        if not line.startswith("data:"):
            continue
        try:
            msg = json.loads(line[5:].strip())
        except json.JSONDecodeError:
            continue
        if isinstance(msg, dict) and msg.get("id") == req_id:
            last = msg
    if last is None:
        raise GatewayError("gateway stream ended without a response")
    return last
