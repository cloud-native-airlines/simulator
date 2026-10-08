"""FastAPI application: control API, the web UI, and the background tick loop."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from .clock import Clock
from .config import Config, _generate_run_id, load_config
from .logging_config import configure_logging

logger = logging.getLogger("simulator")

_STATIC = Path(__file__).parent / "static"


class ClockUpdate(BaseModel):
    speed: float | None = Field(default=None, gt=0)
    tick_interval: float | None = Field(default=None, gt=0)


async def _tick_loop(clock: Clock) -> None:
    """Emit a tick every ``tick_interval`` real seconds while running.

    The loop reads the (live-mutable) interval and paused state each iteration,
    so control-API changes take effect on the next tick without a restart. In
    Phase 1 a tick just advances the sequence number and logs; Phase 2 will
    publish it to the broker here.
    """
    logger.info("tick loop started", extra={"run_id": clock.run_id})
    try:
        while True:
            interval = clock.tick_interval
            if not clock.paused:
                tick_id = clock.advance_tick()
                logger.info(
                    "tick",
                    extra={
                        "run_id": clock.run_id,
                        "tick_id": tick_id,
                        "simulated_at": clock.snapshot()["simulated_at"],
                        "speed": clock.speed,
                    },
                )
            await asyncio.sleep(max(interval, 0.01))
    except asyncio.CancelledError:
        logger.info("tick loop stopped", extra={"run_id": clock.run_id})
        raise


def create_app(config: Config | None = None) -> FastAPI:
    config = config or load_config()
    clock = Clock(
        run_id=config.run_id,
        start_time=config.start_time,
        speed=config.clock_speed,
        tick_interval=config.tick_interval,
        start_paused=config.start_paused,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info(
            "simulator starting",
            extra={
                "run_id": clock.run_id,
                "simulated_at": clock.snapshot()["simulated_at"],
                "speed": clock.speed,
                "tick_interval": clock.tick_interval,
                "paused": clock.paused,
            },
        )
        task = asyncio.create_task(_tick_loop(clock))
        try:
            yield
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    app = FastAPI(title="Cloud Native Airlines Simulator", lifespan=lifespan)
    app.state.clock = clock

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return (_STATIC / "index.html").read_text()

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz() -> dict:
        # Phase 1 has no external dependency; ready once the clock exists.
        return {"status": "ready"}

    @app.get("/clock")
    async def get_clock() -> dict:
        return clock.snapshot()

    @app.patch("/clock")
    async def patch_clock(update: ClockUpdate) -> dict:
        if update.speed is None and update.tick_interval is None:
            raise HTTPException(status_code=400, detail="no fields to update")
        if update.speed is not None:
            clock.set_speed(update.speed)
        if update.tick_interval is not None:
            clock.set_tick_interval(update.tick_interval)
        logger.info("clock updated", extra=clock.snapshot())
        return clock.snapshot()

    @app.post("/control/start")
    @app.post("/control/resume")
    async def resume() -> dict:
        clock.resume()
        logger.info("clock resumed", extra={"run_id": clock.run_id})
        return clock.snapshot()

    @app.post("/control/pause")
    async def pause() -> dict:
        clock.pause()
        logger.info("clock paused", extra={"run_id": clock.run_id})
        return clock.snapshot()

    @app.post("/control/reset")
    async def reset() -> dict:
        new_run_id = _generate_run_id()
        clock.reset(new_run_id)
        logger.info("clock reset", extra={"run_id": clock.run_id})
        return clock.snapshot()

    return app


def build() -> FastAPI:
    """Entry point for ``uvicorn simulator.app:build`` (factory mode)."""
    configure_logging()
    return create_app()
