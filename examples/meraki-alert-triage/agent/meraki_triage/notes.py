"""The text the agent writes into Halo.

Every note has the same parts in the same order, so a technician can read
one in ten seconds and know how far to trust it.
"""
from __future__ import annotations

from html import escape

from meraki_triage.alerts import MerakiAlert
from meraki_triage.triage import Triage

SIGNATURE = "AI Technician (automated triage, governed by Behavry)"

# Halo priority ids, 1 = Critical ... 4 = Low.
PRIORITY_BY_SEVERITY = {"critical": 1, "high": 2, "medium": 3, "low": 4, "info": 4}


def ticket_summary(alert: MerakiAlert, triage: Triage) -> str:
    """Carries the device serial so the next alert for it finds this ticket."""
    serial = f" [{alert.device_serial}]" if alert.device_serial else ""
    return f"Meraki: {triage.headline}{serial}"[:250]


def _p(label: str, body: str) -> str:
    return f"<p><strong>{escape(label)}</strong> {escape(body)}</p>"


def triage_note(alert: MerakiAlert, triage: Triage, *, flagged_fields: list[str]) -> str:
    parts = [
        f"<p><em>{escape(SIGNATURE)}</em></p>",
        _p("What happened:", (
            f"{alert.alert_type or 'Alert'} on {alert.device_label}"
            f" in {alert.network_name or 'an unnamed network'}"
            f" at {alert.occurred_at or 'an unreported time'}."
        )),
        _p("Impact:", f"{triage.impact} (severity: {triage.severity})"),
        _p("What I checked:", "; ".join(triage.checks) or "nothing beyond the alert itself"),
        _p("Likely cause:", triage.likely_cause),
        _p("Recommendation:", triage.recommendation),
        _p("Confidence:", triage.confidence + (
            ". A technician should confirm before acting." if triage.needs_human else "."
        )),
    ]
    if triage.suspicious_content or flagged_fields:
        where = ", ".join(flagged_fields) or triage.suspicious_reason or "the alert text"
        parts.append(_p(
            "Caution:",
            f"Part of this alert reads like an instruction to an AI ({where}). "
            "It was treated as data and no action was taken because of it. "
            "Worth checking who named this device or network.",
        ))
    parts.append(f"<p><small>Meraki alert {escape(alert.stable_id)}</small></p>")
    return "".join(parts)


def recovery_note(alert: MerakiAlert) -> str:
    return (
        f"<p><em>{escape(SIGNATURE)}</em></p>"
        + _p("Update:", f"{alert.device_label} reported back up at {alert.occurred_at or 'an unreported time'}.")
        + f"<p><small>Meraki alert {escape(alert.stable_id)}</small></p>"
    )


def remediation_requested_note(action: str, alert: MerakiAlert) -> str:
    return (
        f"<p><em>{escape(SIGNATURE)}</em></p>"
        + _p("Remediation requested:", (
            f"{action} for {alert.device_label}. This is waiting for a person to "
            "approve it in Behavry; nothing has been done yet."
        ))
    )


def remediation_outcome_note(action: str, outcome: str) -> str:
    return f"<p><em>{escape(SIGNATURE)}</em></p>" + _p(f"{action}:", outcome)
