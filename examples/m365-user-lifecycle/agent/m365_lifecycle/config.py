"""Settings, read once from the environment.

Every secret here belongs in your platform's secret store, wired into the
container as an environment variable.
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


def _int(name: str) -> int | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    return default if not raw else raw in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class ToolNames:
    """Logical tool -> the name your MCP gateway exposes, before Behavry's
    ``<server_id>__`` namespace. Override any one with ``TOOL_<LOGICAL>``.

    The Microsoft 365 tools are a contract, not a product: map them onto the
    Graph MCP server or tenant-management tooling you already run. One rule is
    not negotiable: ``create_user`` has the server set the initial password and
    never return it, so no password passes through the agent, the model, the
    PSA, or the record.
    """

    get_user: str = "m365_get_user"
    create_user: str = "m365_create_user"
    assign_license: str = "m365_assign_license"
    add_group_member: str = "m365_add_group_member"
    disable_user: str = "m365_disable_user"
    revoke_sessions: str = "m365_revoke_sessions"
    convert_mailbox_to_shared: str = "m365_convert_mailbox_to_shared"
    remove_licenses: str = "m365_remove_licenses"
    ticket_note: str = "halo_add_action"

    @classmethod
    def from_env(cls) -> ToolNames:
        defaults = cls()
        return cls(**{
            name: os.environ.get(f"TOOL_{name.upper()}", getattr(defaults, name)).strip()
            for name in defaults.__dataclass_fields__
        })


@dataclass(frozen=True)
class Settings:
    behavry_proxy_url: str
    behavry_client_id: str
    behavry_client_secret: str
    anthropic_api_key: str
    # HMAC key your PSA automation uses to sign each request body.
    webhook_secret: str
    # The MSP-owned JSON catalogue of clients: tenants, domains, licences, groups.
    client_catalog_path: str

    # When set, tools must come from this Behavry registration.
    gateway_server_id: str = ""
    tools: ToolNames = field(default_factory=ToolNames)

    model: str = "claude-opus-5-5"
    effort: str = "medium"
    model_fallbacks: bool = True

    halo_note_actiontype_id: int | None = None

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            behavry_proxy_url=_required("BEHAVRY_PROXY_URL").rstrip("/"),
            behavry_client_id=_required("BEHAVRY_CLIENT_ID"),
            behavry_client_secret=_required("BEHAVRY_CLIENT_SECRET"),
            anthropic_api_key=_required("ANTHROPIC_API_KEY"),
            webhook_secret=_required("WEBHOOK_SECRET"),
            client_catalog_path=_required("CLIENT_CATALOG_PATH"),
            gateway_server_id=os.environ.get("GATEWAY_SERVER_ID", "").strip(),
            tools=ToolNames.from_env(),
            model=os.environ.get("LIFECYCLE_MODEL", "claude-opus-5-5").strip(),
            effort=os.environ.get("LIFECYCLE_EFFORT", "medium").strip(),
            model_fallbacks=_bool("LIFECYCLE_MODEL_FALLBACKS", True),
            halo_note_actiontype_id=_int("HALO_NOTE_ACTIONTYPE_ID"),
        )
