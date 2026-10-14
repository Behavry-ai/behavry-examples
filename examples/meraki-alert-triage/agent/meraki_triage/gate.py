"""The noise gate between Meraki and the triage pipeline.

Technicians stop trusting an agent that opens two tickets for one blip long
before they judge its summaries, so this runs before anything else:

* **Duplicates** (same network, device and alert kind inside the window) are
  dropped. Meraki retries deliveries it thinks failed, and some alerts repeat.
* **Outages are held** for ``hold_seconds``. A recovery for the same device
  inside the hold cancels the outage: the pair is recorded and nothing is
  written to Halo.
* Everything else passes straight through.

State is in memory, so run exactly one replica. That is the right shape for a
PoC; a production version would keep this in Redis or the database.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from meraki_triage.alerts import MerakiAlert


class Verdict(StrEnum):
    PROCESS = "process"
    DUPLICATE = "duplicate"
    HELD = "held"
    FLAPPED = "flapped"


@dataclass(frozen=True)
class GateResult:
    verdict: Verdict
    alert: MerakiAlert
    # For FLAPPED: the outage the recovery cancelled.
    cancelled: MerakiAlert | None = None


class AlertGate:
    def __init__(
        self,
        *,
        hold_seconds: float,
        dedupe_window_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._hold = hold_seconds
        self._window = dedupe_window_seconds
        self._clock = clock
        self._seen: dict[tuple[str, str, str], float] = {}
        self._held: dict[tuple[str, str, str], tuple[float, MerakiAlert]] = {}

    @staticmethod
    def _dedupe_key(alert: MerakiAlert) -> tuple[str, str, str]:
        return (alert.network_id or "", alert.subject, alert.kind.value)

    @staticmethod
    def _pair_key(alert: MerakiAlert) -> tuple[str, str, str]:
        return (alert.network_id or "", alert.subject, alert.kind.family)

    def admit(self, alert: MerakiAlert) -> GateResult:
        now = self._clock()
        self._expire_seen(now)

        key = self._dedupe_key(alert)
        if key in self._seen:
            return GateResult(Verdict.DUPLICATE, alert)
        self._seen[key] = now

        kind = alert.kind
        if kind.is_down and self._hold > 0:
            self._held[self._pair_key(alert)] = (now + self._hold, alert)
            return GateResult(Verdict.HELD, alert)

        if kind.is_up:
            # A recovery clears the outage's dedupe entry, so the next outage
            # for this device is seen fresh rather than as a repeat.
            down_kind = alert.kind.family + "_down"
            self._seen.pop((alert.network_id or "", alert.subject, down_kind), None)
            pending = self._held.pop(self._pair_key(alert), None)
            if pending is not None:
                return GateResult(Verdict.FLAPPED, alert, cancelled=pending[1])

        return GateResult(Verdict.PROCESS, alert)

    def due(self) -> list[MerakiAlert]:
        """Held outages whose hold has run out, oldest first. Each is returned
        once; the caller processes them."""
        now = self._clock()
        ready = sorted(
            ((deadline, key) for key, (deadline, _) in self._held.items() if deadline <= now),
        )
        return [self._held.pop(key)[1] for _, key in ready]

    def _expire_seen(self, now: float) -> None:
        cutoff = now - self._window
        for key in [k for k, t in self._seen.items() if t <= cutoff]:
            del self._seen[key]
