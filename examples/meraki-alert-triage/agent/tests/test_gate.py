from helpers import alert

from meraki_triage.gate import AlertGate, Verdict


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def gate(clock: Clock) -> AlertGate:
    return AlertGate(hold_seconds=300, dedupe_window_seconds=900, clock=clock)


UP = {"alertTypeId": "switches_came_up", "alertType": "Switch came up", "alertId": "2"}


def test_outage_is_held_then_released():
    c = Clock()
    g = gate(c)
    assert g.admit(alert()).verdict is Verdict.HELD
    assert g.due() == []
    c.now += 301
    released = g.due()
    assert [a.stable_id for a in released] == [alert().stable_id]
    assert g.due() == []  # returned once


def test_recovery_inside_hold_cancels_outage():
    c = Clock()
    g = gate(c)
    g.admit(alert())
    c.now += 60
    result = g.admit(alert(**UP))
    assert result.verdict is Verdict.FLAPPED
    assert result.cancelled is not None and result.cancelled.stable_id == alert().stable_id
    c.now += 600
    assert g.due() == []


def test_recovery_after_hold_is_processed():
    c = Clock()
    g = gate(c)
    g.admit(alert())
    c.now += 301
    g.due()
    assert g.admit(alert(**UP)).verdict is Verdict.PROCESS


def test_repeat_inside_window_is_dropped_and_expires():
    c = Clock()
    g = gate(c)
    rogue = {"alertTypeId": "rogue_ap_detected", "alertType": "Rogue AP detected"}
    assert g.admit(alert(**rogue)).verdict is Verdict.PROCESS
    assert g.admit(alert(**rogue, alertId="99")).verdict is Verdict.DUPLICATE
    c.now += 901
    assert g.admit(alert(**rogue, alertId="100")).verdict is Verdict.PROCESS


def test_new_outage_after_recovery_is_not_a_duplicate():
    c = Clock()
    g = gate(c)
    g.admit(alert())
    c.now += 30
    g.admit(alert(**UP))
    c.now += 30
    assert g.admit(alert(alertId="3")).verdict is Verdict.HELD


def test_other_devices_do_not_interfere():
    c = Clock()
    g = gate(c)
    g.admit(alert())
    other_up = alert(**UP, deviceSerial="Q2XX-CCCC-DDDD")
    assert g.admit(other_up).verdict is Verdict.PROCESS
    c.now += 301
    assert len(g.due()) == 1
