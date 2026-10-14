import asyncio

from helpers import alert

from meraki_triage.app import Worker
from meraki_triage.gate import AlertGate


class SlowPipeline:
    """Records start/finish; the first alert for device A blocks until released."""

    def __init__(self):
        self.events = []
        self.release = asyncio.Event()

    async def process(self, a):
        self.events.append(("start", a.stable_id))
        if a.stable_id == "a1":
            await self.release.wait()
        self.events.append(("end", a.stable_id))


ROGUE = {"alertTypeId": "rogue_ap_detected", "alertType": "Rogue AP detected"}


def test_a_held_alert_does_not_block_other_devices_but_serialises_its_own():
    async def go():
        pipe = SlowPipeline()
        w = Worker(AlertGate(hold_seconds=0, dedupe_window_seconds=0), pipe)
        w._start(alert(alertId="a1", **ROGUE))
        w._start(alert(alertId="a2", alertTypeId="uplink_status_changed", alertType="Uplink"))
        w._start(alert(alertId="b1", deviceSerial="Q2XX-OTHER", **ROGUE))
        await asyncio.sleep(0.05)
        # Device B finished while device A's first alert is still waiting;
        # A's second alert has not started.
        assert ("end", "b1") in pipe.events
        assert ("start", "a2") not in pipe.events
        pipe.release.set()
        await w.drain()
        assert pipe.events.index(("end", "a1")) < pipe.events.index(("start", "a2"))

    asyncio.run(go())
