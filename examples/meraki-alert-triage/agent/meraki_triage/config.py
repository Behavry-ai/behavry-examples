"""Settings, read once from the environment.

Every secret here belongs in Key Vault (or the platform's secret store), wired
into the container as an environment variable. Nothing is read from files.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


class ConfigError(ValueError):
    """A required setting is missing or malformed."""


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(f"{name} is required")
    return value


def _int(name: str, default: int | None) -> int | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class ToolNames:
    """Logical tool -> the name the gateway exposes, before Behavry's
    ``<server_id>__`` namespace. Defaults assume the gateway prefixes Halo tools
    with ``halo_`` and Meraki tools with ``meraki_``; confirm against a real
    ``tools/list`` and override per tool with ``TOOL_<LOGICAL>``."""

    search_assets: str = "halo_search_assets"
    list_tickets_by_client: str = "halo_list_tickets_by_client"
    create_ticket: str = "halo_create_ticket"
    update_ticket: str = "halo_update_ticket"
    add_action: str = "halo_add_action"
    reboot_device: str = "meraki_reboot_device"

    @classmethod
    def from_env(cls) -> ToolNames:
        defaults = cls()
        return cls(**{
            name: os.environ.get(f"TOOL_{name.upper()}", getattr(defaults, name)).strip()
            for name in defaults.__dataclass_fields__
        })


@dataclass(frozen=True)
class Settings:
    # Behavry: the plane URL and this agent's own client credentials.
    behavry_proxy_url: str
    behavry_client_id: str
    behavry_client_secret: str
    # Forwarded to Anthropic by Behavry's proxy; Behavry never logs it.
    anthropic_api_key: str
    # Meraki puts this in every webhook body; anything else is rejected.
    meraki_shared_secret: str

    # The Behavry registration id of your MCP gateway target. When set, tools must
    # come from it; when empty, the first gateway tool with a matching name wins.
    gateway_server_id: str = ""
    tools: ToolNames = field(default_factory=ToolNames)

    model: str = "claude-opus-5-5"
    effort: str = "medium"
    # Server-side refusal fallback. Off switch for a proxy that rejects the beta.
    model_fallbacks: bool = True

    # Noise handling.
    flap_hold_seconds: int = 300
    dedupe_window_seconds: int = 900

    # Halo specifics. A private note type keeps triage off the client's email.
    halo_note_actiontype_id: int | None = None
    halo_ticket_type_id: int | None = None
    halo_oncall_agent_id: int | None = None
    halo_oncall_team: str = ""
    # When set, every PoC ticket lands on this client (a sandbox), whatever
    # client the asset lookup finds.
    halo_sandbox_client_id: int | None = None

    # Week 2: ask Behavry to run a remediation. Held for a person by policy.
    allow_remediation_requests: bool = False

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            behavry_proxy_url=_required("BEHAVRY_PROXY_URL").rstrip("/"),
            behavry_client_id=_required("BEHAVRY_CLIENT_ID"),
            behavry_client_secret=_required("BEHAVRY_CLIENT_SECRET"),
            anthropic_api_key=_required("ANTHROPIC_API_KEY"),
            meraki_shared_secret=_required("MERAKI_SHARED_SECRET"),
            gateway_server_id=os.environ.get("GATEWAY_SERVER_ID", "").strip(),
            tools=ToolNames.from_env(),
            model=os.environ.get("TRIAGE_MODEL", "claude-opus-5-5").strip(),
            effort=os.environ.get("TRIAGE_EFFORT", "medium").strip(),
            model_fallbacks=_bool("TRIAGE_MODEL_FALLBACKS", True),
            flap_hold_seconds=_int("FLAP_HOLD_SECONDS", 300) or 0,
            dedupe_window_seconds=_int("DEDUPE_WINDOW_SECONDS", 900) or 0,
            halo_note_actiontype_id=_int("HALO_NOTE_ACTIONTYPE_ID", None),
            halo_ticket_type_id=_int("HALO_TICKET_TYPE_ID", None),
            halo_oncall_agent_id=_int("HALO_ONCALL_AGENT_ID", None),
            halo_oncall_team=os.environ.get("HALO_ONCALL_TEAM", "").strip(),
            halo_sandbox_client_id=_int("HALO_SANDBOX_CLIENT_ID", None),
            allow_remediation_requests=_bool("ALLOW_REMEDIATION_REQUESTS", False),
        )
