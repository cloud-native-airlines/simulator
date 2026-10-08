# Cloud Native Airlines Simulator

Owns simulated time for the Cloud Native Airlines demo. See
[SIMULATOR_PROJECT_GOALS.md](SIMULATOR_PROJECT_GOALS.md) for the vision and
[SIMULATOR_DESIGN.md](SIMULATOR_DESIGN.md) for the design and phased plan.

**Phase 1 (this version):** a standalone clock with a web UI — no broker, no
other services. Open the page, press play, and watch simulated time advance.
Pub/sub tick delivery to aircraft, persistence, and full observability come in
Phase 2.

## Run

### Python

```sh
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"      # drop [dev] for runtime only
python -m simulator
```

Then open <http://localhost:8000>.

### Docker

```sh
docker build -t cna-simulator .
docker run --rm -p 8000:8000 cna-simulator
```

## Configuration

Set via environment variables (all optional):

| Variable | Default | Meaning |
| --- | --- | --- |
| `SIM_START_TIME` | current real UTC | Simulated start time (RFC 3339) |
| `SIM_CLOCK_SPEED` | `60` | Simulated seconds advanced per real second |
| `SIM_TICK_INTERVAL` | `1.0` | Real seconds between ticks |
| `SIM_START_PAUSED` | `true` | Start paused so you can press play |
| `SIM_SCENARIO` | — | Path to a scenario JSON file (supplies `run_id` and start time) |
| `SIM_HOST` / `SIM_PORT` | `0.0.0.0` / `8000` | Listen address |

Start-time resolution order: `SIM_START_TIME` → scenario start → current real UTC.

## API

| Method & path | Purpose |
| --- | --- |
| `GET /` | Web UI |
| `GET /clock` | Current clock snapshot |
| `PATCH /clock` | Set `speed` and/or `tick_interval` live |
| `POST /control/start` · `/control/resume` | Begin / resume advancing |
| `POST /control/pause` | Freeze simulated time |
| `POST /control/reset` | New run ID, restart at the configured start time |
| `GET /healthz` · `/readyz` | Health and readiness |

The clock snapshot:

```json
{
  "run_id": "sim-20261008T161334Z-c06998",
  "simulated_at": "2026-10-08T16:15:06.389Z",
  "real_time": "2026-10-08T16:13:36.001Z",
  "tick_id": 92,
  "speed": 60.0,
  "tick_interval": 1.0,
  "paused": false
}
```

Simulated time advances continuously by `real_elapsed * speed`. Changing speed
only affects future advancement, so the clock never jumps backward; pause freezes
it and resume continues from the same point.

## Test

```sh
pytest
```
