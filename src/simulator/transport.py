"""Tick delivery transports.

The simulator publishes a world-clock pulse that downstream components (aircraft)
consume. Delivery sits behind this small interface so Phase 1 stays dependency-free
(:class:`NoopTransport`) while Phase 2 publishes to NATS (:class:`NatsTransport`).
"""

from __future__ import annotations

import json
import logging
from typing import Protocol

logger = logging.getLogger("simulator")


class TickTransport(Protocol):
    async def start(self) -> None: ...
    async def publish(self, tick: dict) -> None: ...
    async def close(self) -> None: ...


class NoopTransport:
    """Publishes nowhere. Used when no broker is configured (Phase 1)."""

    async def start(self) -> None:
        return None

    async def publish(self, tick: dict) -> None:
        return None

    async def close(self) -> None:
        return None


class NatsTransport:
    """Publishes each tick as JSON to a NATS subject."""

    def __init__(self, url: str, subject: str) -> None:
        self._url = url
        self._subject = subject
        self._nc = None

    async def start(self) -> None:
        import nats  # imported lazily so Phase 1 needs no NATS dependency

        self._nc = await nats.connect(
            self._url,
            max_reconnect_attempts=-1,
            reconnect_time_wait=1,
            name="cna-simulator",
        )
        logger.info("nats connected", extra={"url": self._url, "subject": self._subject})

    async def publish(self, tick: dict) -> None:
        if self._nc is None:
            return
        try:
            await self._nc.publish(self._subject, json.dumps(tick).encode())
        except Exception as exc:  # delivery failures must not stall the clock
            logger.warning("tick publish failed", extra={"error": str(exc)})

    async def close(self) -> None:
        if self._nc is not None:
            try:
                await self._nc.drain()
            except Exception:
                pass
            self._nc = None


def build_transport(nats_url: str | None, subject: str) -> TickTransport:
    if nats_url:
        return NatsTransport(nats_url, subject)
    return NoopTransport()
