"""The request endpoint and the worker that drains it.

    uvicorn m365_lifecycle.app:app --host 0.0.0.0 --port 8080

The PSA posts a signed request; the endpoint checks the signature, drops a
request id it has already seen (PSA automations retry), queues it and replies
at once. Each request runs as its own task, one at a time per client, because
a held step can wait up to 30 minutes for a reviewer and must not stall the
others.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
from collections import OrderedDict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from pydantic import ValidationError

from m365_lifecycle.behavry_mcp import BehavryMCP
from m365_lifecycle.config import Settings
from m365_lifecycle.extract import ClaudeExtractor
from m365_lifecycle.intake import SIGNATURE_HEADER, Catalog, LifecycleRequest, verify_signature
from m365_lifecycle.pipeline import REQUIRED_TOOLS, Pipeline

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format='{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
)
logger = logging.getLogger("m365_lifecycle")

QUEUE_SIZE = 500
SEEN_LIMIT = 5000


class Worker:
    def __init__(self, pipeline: Pipeline) -> None:
        self.pipeline = pipeline
        self.queue: asyncio.Queue[LifecycleRequest] = asyncio.Queue(maxsize=QUEUE_SIZE)
        self._seen: OrderedDict[str, None] = OrderedDict()
        self._locks: dict[int, asyncio.Lock] = {}
        self._tasks: set[asyncio.Task[None]] = set()

    def accept(self, req: LifecycleRequest) -> bool:
        """Queue a request once. False for a repeat delivery."""
        if req.request_id in self._seen:
            return False
        self.queue.put_nowait(req)
        self._seen[req.request_id] = None
        while len(self._seen) > SEEN_LIMIT:
            self._seen.popitem(last=False)
        return True

    async def run(self) -> None:
        while True:
            req = await self.queue.get()
            task = asyncio.create_task(self._safe(req), name=f"request-{req.request_id}")
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def _safe(self, req: LifecycleRequest) -> None:
        lock = self._locks.setdefault(req.client_id, asyncio.Lock())
        try:
            async with lock:
                await self.pipeline.process(req)
        except Exception:  # one bad request must not stop the others
            logger.exception("request %s: processing failed", req.request_id)

    async def drain(self) -> None:
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    s = Settings.from_env()
    catalog = Catalog.load(s.client_catalog_path)
    mcp = BehavryMCP(s.behavry_proxy_url, s.behavry_client_id, s.behavry_client_secret)
    missing = await mcp.resolve_tools({k: getattr(s.tools, k) for k in REQUIRED_TOOLS},
                                      server_id=s.gateway_server_id)
    if missing:
        raise RuntimeError(
            "These tools are not in this agent's Behavry catalogue: "
            + ", ".join(f"{k} (looked for {v})" for k, v in missing.items())
            + ". Check the gateway registration and the TOOL_* overrides."
        )
    extractor = ClaudeExtractor(
        proxy_url=s.behavry_proxy_url, client_id=s.behavry_client_id, client_secret=s.behavry_client_secret,
        anthropic_api_key=s.anthropic_api_key, model=s.model, effort=s.effort, fallbacks=s.model_fallbacks,
    )
    worker = Worker(Pipeline(s, mcp, extractor, catalog))
    app.state.settings, app.state.worker = s, worker
    task = asyncio.create_task(worker.run(), name="lifecycle-worker")
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


app = FastAPI(title="Microsoft 365 lifecycle agent (Behavry reference)", lifespan=lifespan)


@app.get("/healthz")
async def healthz(request: Request) -> dict[str, object]:
    return {"ok": True, "queued": request.app.state.worker.queue.qsize()}


@app.post("/requests")
async def lifecycle_request(request: Request) -> dict[str, object]:
    body = await request.body()
    if not verify_signature(body, request.headers.get(SIGNATURE_HEADER), request.app.state.settings.webhook_secret):
        raise HTTPException(status_code=401, detail="bad signature")
    try:
        req = LifecycleRequest.model_validate(json.loads(body))
    except (ValueError, ValidationError) as exc:
        raise HTTPException(status_code=400, detail="not a lifecycle request") from exc
    try:
        queued = request.app.state.worker.accept(req)
    except asyncio.QueueFull as exc:
        raise HTTPException(status_code=503, detail="queue full") from exc
    return {"queued": queued, "request": req.request_id}
