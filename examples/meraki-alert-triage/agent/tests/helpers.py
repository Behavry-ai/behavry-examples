from __future__ import annotations

from typing import Any

from meraki_triage.alerts import MerakiAlert


def alert(**overrides: Any) -> MerakiAlert:
    payload: dict[str, Any] = {
        "version": "0.1",
        "sharedSecret": "s3cret",
        "organizationName": "Acme MSP",
        "networkId": "N_1",
        "networkName": "Clinic HQ",
        "deviceSerial": "Q2XX-AAAA-BBBB",
        "deviceName": "HQ-SW-01",
        "deviceModel": "MS120-8",
        "alertId": "643451796765234567",
        "alertType": "Switch went down",
        "alertTypeId": "switches_went_down",
        "alertLevel": "critical",
        "occurredAt": "2026-10-14T15:00:00.000000Z",
        "alertData": {},
    }
    payload.update(overrides)
    return MerakiAlert.model_validate(payload)
