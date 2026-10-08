"""Startup configuration.

Three layers feed the simulator (see SIMULATOR_DESIGN.md): an optional scenario
file (the world), environment variables (startup defaults), and the control API
(live changes). This module resolves the first two into a :class:`Config`.

Start-time resolution order: ``SIM_START_TIME`` -> scenario start -> current real
UTC. (Restored persisted state will slot in ahead of these in Phase 2.)
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class Config:
    run_id: str
    start_time: datetime
    clock_speed: float
    tick_interval: float
    start_paused: bool
    scenario_path: str | None
    host: str
    port: int


def _parse_rfc3339(value: str) -> datetime:
    dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _generate_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"sim-{stamp}-{uuid.uuid4().hex[:6]}"


def load_config(env: dict[str, str] | None = None) -> Config:
    env = dict(os.environ if env is None else env)

    scenario_path = env.get("SIM_SCENARIO")
    scenario: dict = {}
    if scenario_path:
        scenario = json.loads(Path(scenario_path).read_text())

    # run_id: scenario wins, else generated.
    run_id = scenario.get("run_id") or _generate_run_id()

    # start_time: SIM_START_TIME -> scenario start -> now.
    if env.get("SIM_START_TIME"):
        start_time = _parse_rfc3339(env["SIM_START_TIME"])
    elif scenario.get("departure_time"):
        start_time = _parse_rfc3339(scenario["departure_time"])
    else:
        start_time = datetime.now(timezone.utc)

    return Config(
        run_id=run_id,
        start_time=start_time,
        clock_speed=float(env.get("SIM_CLOCK_SPEED", "60")),
        tick_interval=float(env.get("SIM_TICK_INTERVAL", "1.0")),
        start_paused=_env_bool("SIM_START_PAUSED", True),
        scenario_path=scenario_path,
        host=env.get("SIM_HOST", "0.0.0.0"),
        port=int(env.get("SIM_PORT", "8000")),
    )
