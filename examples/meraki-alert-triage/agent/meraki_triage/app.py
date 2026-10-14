"""The webhook receiver and the worker that drains it.

Meraki wants a quick 2xx, so the endpoint only checks the shared secret and
queues the alert; triage happens in a background worker. Run one replica: the
noise gate keeps its state in memory.

    uvicorn meraki_triage.app:app --host 0.0.0.0 --port 8080
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from pydantic import ValidationError

from meraki_triage.alerts import MerakiAlert, verify_shared_secret
from meraki_triage.behavry_mcp import BehavryMCP
from meraki_triage.config import Settings
from meraki_triage.gate import AlertGate, Verdict
from meraki_triage.pipeline import REQUIRED_TOOLS, Pipeline
from meraki_triage.triage import ClaudeTriager

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format='{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
)
logger = logging.getLogger("meraki_triage")

QUEUE_SIZE = 1000
TICK_SECONDS = 5.0


class Worker:
    """Drains the queue through the gate and runs each admitted alert as its
    own task. A held remediation can wait up to 30 minutes for a reviewer, so
    alerts must not run one after another; alerts for the same device do, so
    two of them never race to open the same ticket."""

    def __init__(self, gate: AlertGate, pipeline: Pipeline) -> None:
        self.gate = gate
        self.pipeline = pipeline
        self.queue: asyncio.Queue[MerakiAlert] = asyncio.Queue(maxsize=QUEUE_SIZE)
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}
        self._tasks: set[asyncio.Task[None]] = set()

    def _start(self, alert: MerakiAlert) -> None:
        task = asyncio.create_task(self._safe_process(alert), name=f"alert-{alert.stable_id}")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def drain(self) -> None:
        """Wait for in-flight alerts (tests and shutdown)."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def run(self) -> None:
        while True:
            try:
                alert = await asyncio.wait_for(self.queue.get(), timeout=TICK_SECONDS)
            except TimeoutError:
                alert = None
            if alert is not None:
                result = self.gate.admit(alert)
                logger.info("alert %s (%s): %s", alert.stable_id, alert.kind.value, result.verdict.value)
                if result.verdict is Verdict.PROCESS:
                    self._start(alert)
                elif result.verdict is Verdict.FLAPPED and result.cancelled is not None:
                    logger.info(
                        "alert %s recovered inside the hold; outage %s cancelled, nothing written",
                        alert.stable_id, result.cancelled.stable_id,
                    )
            for held in self.gate.due():
                self._start(held)

    async def _safe_process(self, alert: MerakiAlert) -> None:
        lock = self._locks.setdefault((alert.network_id or "", alert.subject), asyncio.Lock())
        try:
            async with lock:
                await self.pipeline.process(alert)
        except Exception:  # one bad alert must not stop the others
            logger.exception("alert %s: processing failed", alert.stable_id)


def build(settings: Settings) -> tuple[BehavryMCP, Worker]:
    mcp = BehavryMCP(settings.behavry_proxy_url, settings.behavry_client_id, settings.behavry_client_secret)
    triager = ClaudeTriager(
        proxy_url=settings.behavry_proxy_url,
        client_id=settings.behavry_client_id,
        client_secret=settings.behavry_client_secret,
        anthropic_api_key=settings.anthropic_api_key,
        model=settings.model,
        effort=settings.effort,
        fallbacks=settings.model_fallbacks,
    )
    gate = AlertGate(
        hold_seconds=settings.flap_hold_seconds,
        dedupe_window_seconds=settings.dedupe_window_seconds,
    )
    return mcp, Worker(gate, Pipeline(settings, mcp, triager))


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = Settings.from_env()
    mcp, worker = build(settings)

    wanted = {key: getattr(settings.tools, key) for key in REQUIRED_TOOLS}
    if settings.allow_remediation_requests:
        wanted["reboot_device"] = settings.tools.reboot_device
    missing = await mcp.resolve_tools(wanted, server_id=settings.gateway_server_id)
    required_missing = {k: v for k, v in missing.items() if k in REQUIRED_TOOLS}
    if required_missing:
        raise RuntimeError(
            "These tools are not in this agent's Behavry catalogue: "
            + ", ".join(f"{k} (looked for {v})" for k, v in required_missing.items())
            + ". Check the gateway registration and the TOOL_* overrides."
        )
    if "reboot_device" in missing:
        logger.warning("remediation is enabled but %s was not found; it stays off", missing["reboot_device"])

    app.state.settings = settings
    app.state.worker = worker
    task = asyncio.create_task(worker.run(), name="triage-worker")
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        for t in list(worker._tasks):
            t.cancel()
        await worker.drain()
        await mcp.aclose()


app = FastAPI(title="Meraki triage agent (Behavry reference)", lifespan=lifespan)


@app.get("/healthz")
async def healthz(request: Request) -> dict[str, object]:
    return {"ok": True, "queued": request.app.state.worker.queue.qsize()}


@app.post("/webhooks/meraki")
async def meraki_webhook(request: Request) -> dict[str, object]:
    try:
        alert = MerakiAlert.model_validate(await request.json())
    except (ValueError, ValidationError) as exc:
        raise HTTPException(status_code=400, detail="not a Meraki alert payload") from exc
    if not verify_shared_secret(alert, request.app.state.settings.meraki_shared_secret):
        raise HTTPException(status_code=401, detail="shared secret mismatch")
    try:
        request.app.state.worker.queue.put_nowait(alert)
    except asyncio.QueueFull as exc:
        # Meraki retries; better than accepting an alert we will not process.
        raise HTTPException(status_code=503, detail="queue full") from exc
    return {"queued": True, "alert": alert.stable_id}
