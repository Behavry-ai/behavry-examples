"""Incoming joiner and leaver requests, and the client catalogue.

A request arrives from your PSA's automation when a "new starter" or "leaver"
ticket is raised: the ticket and client ids, the request type, and whatever the
client's HR contact typed into the form. The body is signed with HMAC-SHA256
(``X-Signature-256: sha256=<hex>``) using a secret only the PSA and the agent
hold.

The catalogue is the MSP's own record of each client: its Microsoft 365
tenant, the domains the agent may act in, the licence to assign, and the
standard groups per department. The model never decides any of this; it only
reads the form.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SIGNATURE_HEADER = "X-Signature-256"


class LifecycleRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    request_id: str = Field(min_length=1, max_length=128)
    ticket_id: int
    client_id: int
    kind: Literal["joiner", "leaver"]
    # Whatever the client submitted: free text or form fields. Untrusted.
    form: dict[str, Any] | str
    submitted_by: str | None = None


def verify_signature(body: bytes, header: str | None, secret: str) -> bool:
    """Constant-time HMAC check. A missing secret or header accepts nothing."""
    if not secret or not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(header.removeprefix("sha256="), expected)


def sign(body: bytes, secret: str) -> str:
    """The header value for ``body`` (for tests and your PSA automation)."""
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


class ClientEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    tenant_id: str
    domains: list[str] = Field(min_length=1)
    usage_location: str = "US"
    license_sku: str
    # Department name -> the standard groups a new starter there joins.
    departments: dict[str, list[str]]
    # Groups every new starter joins, whatever the department.
    baseline_groups: list[str] = Field(default_factory=list)


class Catalog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clients: dict[str, ClientEntry]

    @classmethod
    def load(cls, path: str | Path) -> Catalog:
        return cls.model_validate(json.loads(Path(path).read_text()))

    def for_client(self, client_id: int) -> ClientEntry | None:
        return self.clients.get(str(client_id))
