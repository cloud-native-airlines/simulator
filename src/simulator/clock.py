"""The simulated clock.

The clock keeps simulated time separate from real time. Simulated time advances
by ``real_elapsed * speed``, anchored to a monotonic reference so that:

* changing speed only affects *future* advancement (the clock never jumps backward);
* pause freezes simulated time; resume continues from where it froze;
* clock speed and tick interval are independent.

A tick *samples* the clock: ``simulated_at`` reflects the value latched at the
last tick, so consumers (aircraft, the UI) see time advance in discrete
tick-sized steps — that is what a tick delivers. An internal continuous clock
(``_compute_now``) drives advancement and re-anchoring but is not observed
directly. ``tick_id`` is a monotonic sequence number within a run.

The monotonic source is injectable so the advancement math can be tested
deterministically without real sleeps.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

MonotonicFn = Callable[[], float]


def to_rfc3339(dt: datetime) -> str:
    """Render a UTC datetime as RFC 3339 with a ``Z`` suffix."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class Clock:
    def __init__(
        self,
        *,
        run_id: str,
        start_time: datetime,
        speed: float,
        tick_interval: float,
        start_paused: bool,
        monotonic: MonotonicFn = time.monotonic,
    ) -> None:
        if speed <= 0:
            raise ValueError("speed must be positive")
        if tick_interval <= 0:
            raise ValueError("tick_interval must be positive")
        if start_time.tzinfo is None:
            raise ValueError("start_time must be timezone-aware (UTC)")

        self._monotonic = monotonic
        self._run_id = run_id
        # The configured starting time a reset returns to.
        self._reset_time = start_time.astimezone(timezone.utc)
        self._start_paused = bool(start_paused)

        self._speed = float(speed)
        self._tick_interval = float(tick_interval)
        self._paused = bool(start_paused)
        self._tick_id = 0

        # Anchor: continuous simulated time == _anchor_sim at monotonic instant
        # _anchor_real.
        self._anchor_sim = self._reset_time
        self._anchor_real = self._monotonic()
        # Observable (delivered) time: the continuous clock sampled at the last
        # tick. Starts at the anchor until the first tick lands.
        self._ticked_sim = self._reset_time

    # --- derived state -------------------------------------------------------

    def _compute_now(self) -> datetime:
        """The true continuous simulated time — the internal clock."""
        if self._paused:
            return self._anchor_sim
        elapsed = self._monotonic() - self._anchor_real
        return self._anchor_sim + timedelta(seconds=elapsed * self._speed)

    @property
    def simulated_at(self) -> datetime:
        """The observable simulated time: the value sampled at the last tick.

        Consumers see time advance in discrete tick-sized steps, matching what a
        tick delivers — not the smooth internal clock.
        """
        return self._ticked_sim

    @property
    def run_id(self) -> str:
        return self._run_id

    @property
    def tick_id(self) -> int:
        return self._tick_id

    @property
    def speed(self) -> float:
        return self._speed

    @property
    def tick_interval(self) -> float:
        return self._tick_interval

    @property
    def paused(self) -> bool:
        return self._paused

    # --- mutations -----------------------------------------------------------

    def _reanchor(self) -> None:
        """Pin the anchor to the current continuous time, so a subsequent speed
        or pause change takes effect without moving time."""
        self._anchor_sim = self._compute_now()
        self._anchor_real = self._monotonic()

    def pause(self) -> None:
        if not self._paused:
            self._reanchor()
            self._paused = True

    def resume(self) -> None:
        if self._paused:
            # Re-pin the real anchor to now so the paused span adds no elapsed time.
            self._anchor_real = self._monotonic()
            self._paused = False

    def set_speed(self, speed: float) -> None:
        if speed <= 0:
            raise ValueError("speed must be positive")
        self._reanchor()
        self._speed = float(speed)

    def set_tick_interval(self, tick_interval: float) -> None:
        # Tick interval does not affect simulated time, so no reanchor is needed.
        if tick_interval <= 0:
            raise ValueError("tick_interval must be positive")
        self._tick_interval = float(tick_interval)

    def advance_tick(self) -> int:
        """Sample the clock for a new tick and return the new tick_id.

        Latches the continuous time into the observable ``simulated_at``, so the
        delivered time steps forward once per tick rather than continuously.
        """
        self._ticked_sim = self._compute_now()
        self._tick_id += 1
        return self._tick_id

    def reset(self, run_id: str) -> None:
        """Begin a new run at the configured starting time."""
        self._run_id = run_id
        self._tick_id = 0
        self._paused = self._start_paused
        self._anchor_sim = self._reset_time
        self._anchor_real = self._monotonic()
        self._ticked_sim = self._reset_time

    # --- snapshot ------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        return {
            "run_id": self._run_id,
            "simulated_at": to_rfc3339(self.simulated_at),
            "real_time": to_rfc3339(datetime.now(timezone.utc)),
            "tick_id": self._tick_id,
            "speed": self._speed,
            "tick_interval": self._tick_interval,
            "paused": self._paused,
        }
