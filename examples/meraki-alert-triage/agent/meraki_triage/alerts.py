"""Meraki webhook payloads: parsing, authentication, classification.

Meraki sends one JSON object per alert and puts the shared secret configured
on the webhook receiver in the body (``sharedSecret``). Field names below are
Meraki's; anything else in the payload is kept in ``extra`` untouched.

Classification is by keyword on ``alertTypeId`` / ``alertType`` rather than an
exhaustive id list: confirm the mapping against real payloads from your
networks (Dashboard -> Network-wide -> Alerts -> "Send test webhook") before
relying on it, and add rows to ``_RULES`` as needed.
"""
from __future__ import annotations

import hashlib
import hmac
import re
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AlertKind(StrEnum):
    DEVICE_DOWN = "device_down"
    DEVICE_UP = "device_up"
    VPN_DOWN = "vpn_down"
    VPN_UP = "vpn_up"
    UPLINK_CHANGE = "uplink_change"
    ROGUE_AP = "rogue_ap"
    OTHER = "other"

    @property
    def family(self) -> str:
        """Down/up pairs share a family, so a recovery can cancel its outage."""
        return self.value.rsplit("_", 1)[0] if self in _PAIRED else self.value

    @property
    def is_down(self) -> bool:
        return self in (AlertKind.DEVICE_DOWN, AlertKind.VPN_DOWN)

    @property
    def is_up(self) -> bool:
        return self in (AlertKind.DEVICE_UP, AlertKind.VPN_UP)


_PAIRED = {AlertKind.DEVICE_DOWN, AlertKind.DEVICE_UP, AlertKind.VPN_DOWN, AlertKind.VPN_UP}


class MerakiAlert(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")

    version: str | None = None
    shared_secret: str = Field(default="", alias="sharedSecret", repr=False)
    sent_at: str | None = Field(default=None, alias="sentAt")
    organization_id: str | None = Field(default=None, alias="organizationId")
    organization_name: str | None = Field(default=None, alias="organizationName")
    network_id: str | None = Field(default=None, alias="networkId")
    network_name: str | None = Field(default=None, alias="networkName")
    device_serial: str | None = Field(default=None, alias="deviceSerial")
    device_mac: str | None = Field(default=None, alias="deviceMac")
    device_name: str | None = Field(default=None, alias="deviceName")
    device_model: str | None = Field(default=None, alias="deviceModel")
    alert_id: str | None = Field(default=None, alias="alertId")
    alert_type: str | None = Field(default=None, alias="alertType")
    alert_type_id: str | None = Field(default=None, alias="alertTypeId")
    alert_level: str | None = Field(default=None, alias="alertLevel")
    occurred_at: str | None = Field(default=None, alias="occurredAt")
    alert_data: dict[str, Any] = Field(default_factory=dict, alias="alertData")

    @property
    def kind(self) -> AlertKind:
        return classify(self)

    @property
    def subject(self) -> str:
        """What the alert is about: the device, else the network."""
        return self.device_serial or self.device_mac or self.network_id or "unknown"

    @property
    def device_label(self) -> str:
        name = self.device_name or self.device_serial or "unnamed device"
        return f"{name} ({self.device_serial})" if self.device_serial and self.device_name else name

    @property
    def stable_id(self) -> str:
        """Meraki's alert id, or a digest of what makes this alert itself."""
        if self.alert_id:
            return self.alert_id
        basis = "|".join(str(x) for x in (
            self.network_id, self.subject, self.alert_type_id, self.occurred_at,
        ))
        return hashlib.sha256(basis.encode()).hexdigest()[:16]

    def for_model(self) -> dict[str, Any]:
        """The payload the model may see: everything except the secret."""
        return self.model_dump(by_alias=True, exclude={"shared_secret"}, exclude_none=True)


def verify_shared_secret(alert: MerakiAlert, expected: str) -> bool:
    """Constant-time comparison. An empty expected secret accepts nothing."""
    if not expected:
        return False
    return hmac.compare_digest(alert.shared_secret.encode(), expected.encode())


# (pattern on "<alertTypeId> <alertType>" lowercased, kind). First match wins;
# order matters ("came up" before the generic "vpn").
_RULES: list[tuple[re.Pattern[str], AlertKind]] = [
    (re.compile(r"rogue"), AlertKind.ROGUE_AP),
    (re.compile(r"uplink"), AlertKind.UPLINK_CHANGE),
    (re.compile(r"(went[ _]down|is[ _]down|went[ _]offline)"), AlertKind.DEVICE_DOWN),
    (re.compile(r"(came[ _]up|back[ _]up|back[ _]online|is[ _]up)"), AlertKind.DEVICE_UP),
]


def classify(alert: MerakiAlert) -> AlertKind:
    text = f"{alert.alert_type_id or ''} {alert.alert_type or ''}".lower()
    if "vpn" in text:
        connectivity = alert.alert_data.get("connectivity")
        if isinstance(connectivity, bool):
            return AlertKind.VPN_UP if connectivity else AlertKind.VPN_DOWN
        if isinstance(connectivity, str):
            return AlertKind.VPN_UP if connectivity.lower() in {"true", "up"} else AlertKind.VPN_DOWN
        return AlertKind.VPN_DOWN
    for pattern, kind in _RULES:
        if pattern.search(text):
            return kind
    return AlertKind.OTHER


# Text an outsider can set (a device name, an SSID, a client hostname) that
# reads like an instruction to an AI. Illustrative, not exhaustive: a phrase
# list is easy to word around, which is why it only flags. A fuzzy check
# should send the alert to a person, never drop it, and it is one layer of
# several: the prompt fences the alert as data, the model reports suspicious
# content independently, and Behavry policy holds any action regardless.
_INSTRUCTION_LIKE = re.compile(
    r"(ignore|disregard|forget)\s+(all|any|the|previous|prior|above)"
    r"|system\s*prompt|you\s+are\s+now|as\s+an\s+ai|new\s+instructions"
    r"|\b(assistant|system)\s*:"
    r"|\b(reboot|wipe|delete|reset|run)\s+(the|all|every|this)\b",
    re.IGNORECASE,
)


def instruction_like_fields(alert: MerakiAlert) -> list[str]:
    """Paths of string fields in the alert that look like instructions."""
    hits: list[str] = []

    def walk(value: Any, path: str) -> None:
        if isinstance(value, str):
            if _INSTRUCTION_LIKE.search(value):
                hits.append(path)
        elif isinstance(value, dict):
            for k, v in value.items():
                walk(v, f"{path}.{k}" if path else str(k))
        elif isinstance(value, list):
            for i, v in enumerate(value):
                walk(v, f"{path}[{i}]")

    walk(alert.for_model(), "")
    return hits
