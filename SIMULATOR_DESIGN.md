# Cloud Native Airlines Simulator — Design & Plan

Companion to [SIMULATOR_PROJECT_GOALS.md](SIMULATOR_PROJECT_GOALS.md). This records the
design decisions for the first version and the plan to build it.

## Decisions at a glance

| Topic | Decision | Rationale |
| --- | --- | --- |
| Language / framework | Python + FastAPI | Per goals; room for later demand/economy models. |
| Phasing | **Phase 1 = standalone clock + web UI, no broker.** Pub/sub added in Phase 2. | Get a clickable "push play, watch time advance" demo working with nothing but Python/Docker before adding infrastructure. |
| Tick delivery | **Pub/sub via NATS JetStream (Phase 2)** | Decoupled, cloud-native, rich broker metrics; aircraft are independent pods. In Phase 1 the only consumer of time is the web UI. |
| Web interface | **Lightweight HTML page served by the simulator** | Shows current simulated time; play/pause and ± buttons for speed and tick interval. The Phase 1 acceptance demo. |
| Clock state | **In-memory in Phase 1; persisted in Phase 2 for reliability** | Simulator is the source of truth for *time*. Persistence exists so a simulator pod restart does not lose the whole run (see Persistence). |
| Default start time | **`now` (real UTC at startup)**, unless the scenario specifies one or persisted state is restored | A bare `python main.py` gives a sensible running clock with no scenario file. |
| Live reconfiguration | **Yes — speed, tick interval, pause/resume, reset without restart** | Control API mutates clock state that the tick loop reads each iteration. |
| Pause behavior | **Keep publishing ticks with unchanged `simulated_at` and `paused: true`** | Keeps ADS-B reports fresh so a paused flight reads as *paused*, not *crashed/lost*, on the map. (Applies once pub/sub exists in Phase 2.) |

The broker is the only component that changes if we later prefer Redis Streams or Kafka;
publishing sits behind a small `TickTransport` interface.

## Clock model

The simulator owns a single in-process clock, separate from real time.

- `simulated_at` advances each loop iteration by `(real_now - real_last) * clock_speed`.
  It is **never** advanced by a fixed per-tick increment — that is what keeps a duplicated
  or missed tick from corrupting time.
- `clock_speed` = simulated seconds per real second (e.g. `60` → 1 real second = 1 sim minute).
- `tick_interval` = real seconds between published ticks. Independent of speed: speed changes
  how fast flights progress; interval changes reporting frequency / load.
- `tick_id` = monotonic sequence number within a run, incremented per published tick.
- Changing speed only affects *future* advancement; it recomputes nothing in the past, so the
  clock can never jump backward.

The loop, each iteration:
1. Read current (live-mutable) `clock_speed`, `tick_interval`, `paused`.
2. Advance `simulated_at` by elapsed real time × speed (skip if paused).
3. Build the tick message, publish it (bounded by a deadline — never block the clock on a slow
   broker), increment `tick_id`.
4. Sleep `tick_interval`.

## Configuration

Three layers, each for a different kind of change:

1. **Scenario file** (the world, *optional*) — e.g. [scenarios/msp-ord.json](../cloud-native-airlines/scenarios/msp-ord.json):
   `run_id`, flight plan, origin/destination, scenario start time. Loaded at startup; changed
   only via reset. Versioned in the main repo. Aircraft also read the scenario for their route.
   When no scenario is given, the simulator starts a run at the current real UTC time with a
   generated `run_id` — enough to run the clock and the web UI on their own.
2. **Environment** (startup defaults):
   - `SIM_START_TIME` (RFC 3339; default: current real UTC)
   - `SIM_CLOCK_SPEED` (default `60`)
   - `SIM_TICK_INTERVAL` (seconds, default `1.0`)
   - `SIM_START_PAUSED` (default `true`)
   - `SIM_SCENARIO` (path to a scenario file; optional)
   - `SIM_PUBLISH_DEADLINE` (seconds, default `0.5`) — Phase 2
   - `NATS_URL`, tick subject/stream names — Phase 2
   - `OTEL_EXPORTER_OTLP_ENDPOINT` (optional)
3. **Control API** (live changes, no restart) — see below.

**Start-time resolution order** at startup: restored persisted state (Phase 2) → `SIM_START_TIME`
→ scenario file start time → current real UTC.

## Tick delivery (NATS JetStream)

The simulator **publishes a world-clock pulse**; it does not call aircraft directly. Each
aircraft is an independent durable consumer that maps the pulse onto its own assigned flight
plan. For one aircraft this is a fanout of one; it scales to the fleet with no simulator change.

**Stream / subject**
- Stream `SIM_TICKS`, subject `cna.sim.tick`.
- Short retention (recent messages / short age). Ticks are near-ephemeral: because aircraft
  compute state from the *absolute* `simulated_at`, a reconnecting aircraft only needs the
  **latest** tick, not a replay of every missed one. Consumers use a deliver-last/deliver-new
  policy so a restarted aircraft immediately gets current time.

**Tick message**
```json
{
  "run_id": "msp-ord-demo-2026-10-06",
  "tick_id": 42,
  "simulated_at": "2026-10-06T14:07:00Z",
  "paused": false,
  "speed": 60,
  "tick_interval_s": 1.0
}
```
W3C `traceparent` is set in the NATS message headers so an aircraft's consume span links to the
publish span, and onward to the ADS-B ingestion span.

**Idempotency** — aircraft recompute position/altitude/speed/heading/status purely from
`simulated_at` + their flight plan. At-least-once delivery is therefore safe: a duplicate tick
produces the same state (no double-move), and a missed tick is self-correcting (the next tick
carries the correct absolute time).

**Run identity & reset** — `run_id` travels in every message. On reset the simulator mints a new
`run_id` and starts a new run at the scenario start time. Aircraft adopt the newest `run_id` they
see and reset their own state when it changes, so reports from different runs stay distinguishable
(ADS-B keys on `(run_id, report_id)`).

**Pause** — while paused the loop keeps publishing at `tick_interval` with `simulated_at` frozen
and `paused: true`. Aircraft keep re-reporting their (unchanged) position, so ADS-B freshness does
not decay — a paused aircraft looks parked/held, not lost.

**Failure visibility** (goal: failures visible, world keeps advancing)
- *Simulator → broker*: publish has a deadline and runs off the critical path; publish
  success/failure is a metric, and the clock advances even if the broker is briefly unreachable
  (publishes retry).
- *Broker → fleet*: JetStream per-consumer **pending / unacked / redelivery** counts are the
  "is the fleet keeping up?" signal, scraped as metrics.
- *Demo narrative*: kill an aircraft pod → it stops consuming → its ADS-B reports go stale → the
  flight tracker shows it frozen while other aircraft keep moving; the simulator and broker keep
  running. A slow consumer shows rising pending; a faster tick rate / larger fleet raises load.

## Control API (FastAPI)

All changes take effect on the next loop iteration — no restart.

| Method & path | Effect |
| --- | --- |
| `GET /clock` | Current run_id, simulated_at, tick_id, speed, tick_interval, paused |
| `POST /control/start` | Begin advancing (if started paused) |
| `POST /control/pause` | Freeze `simulated_at` (keeps publishing frozen ticks) |
| `POST /control/resume` | Resume advancing from the current `simulated_at` |
| `PATCH /clock` | Set `speed` and/or `tick_interval` live |
| `POST /control/reset` | New `run_id`, restart at scenario start time |
| `GET /healthz` / `GET /readyz` | Process health; `readyz` checks NATS connectivity |

## Web interface

The simulator serves a single lightweight HTML page at `GET /` (static HTML + a little vanilla
JS, no build step). It is the Phase 1 acceptance demo: open `localhost:<port>`, press play, watch
simulated time advance.

It shows and controls:

- **Current simulated time** — large, live-updating (`GET /clock`, polled ~1 s or via SSE).
- **Play / Pause** — calls `/control/start` · `/control/resume` / `/control/pause`.
- **Clock speed** with **+ / −** buttons — steps through sensible values (e.g. 1, 2, 5, 10, 30,
  60, 120, 300 ×) via `PATCH /clock`.
- **Tick interval** with **+ / −** buttons — adjusts real seconds between ticks via `PATCH /clock`.

The page also shows `run_id`, `tick_id`, and paused state so the operator can see the clock is
actually running. It is a thin view over the same control API — no logic lives only in the page.

## Persistence

The goal of persistence is **reliability**: if the simulator pod dies and restarts, the run
should resume where it left off rather than the whole simulated world being lost.

**Phase 1: none.** Clock state is in memory. A restart starts a fresh run (default start time =
`now`). This keeps the first version a single process with no dependencies.

**Phase 2: persist clock state for restart survival.** Write `run_id`, `simulated_at`, `tick_id`,
`speed`, `tick_interval`, and `paused` to a small store on state change / every N ticks. On boot,
restore it if present (first in the start-time resolution order above) so the simulator rejoins
its run mid-flight; aircraft, already keyed on `run_id`, continue seamlessly. Store choice: SQLite
or a JSON file on a mounted volume for local/compose; the same shape maps to a PVC or external
store under Kubernetes later. A run ledger (runs + optional tick audit log) is a further step if
we want replay/inspection.

## Observability

- **Metrics**: tick processing duration, real elapsed between ticks, current simulated time,
  current speed, publishes attempted/succeeded/failed, publish latency; JetStream consumer
  pending/unacked/redelivery (fleet keep-up). Answers the three operator questions from the goals.
- **Logs**: structured JSON carrying `run_id` and `tick_id` on every tick and control action.
- **Traces**: a span per tick publish, trace context propagated via NATS headers so tick →
  aircraft consume → ADS-B ingest form one tree where those paths are instrumented.

## Build plan

### Phase 1 — standalone clock + web UI (no broker)

1. **Skeleton** — FastAPI app, config loading (env, optional scenario file), `/healthz`
   `/readyz`, repo scaffolding, `requirements`/`pyproject`, Dockerfile.
2. **Clock core** — the clock object + advancement math; unit tests for speed changes (no
   backward jumps), pause/resume preserving time, interval independent of speed, default start =
   `now`.
3. **Control API** — `GET /clock`, `PATCH /clock`, `/control/{start,pause,resume,reset}` wired to
   live-mutate clock state while the loop runs.
4. **Web interface** — the HTML page at `GET /`: live simulated time, play/pause, speed ±,
   interval ±.
5. **Runnable** — `python -m simulator` and `docker run`; documented so `localhost:<port>` →
   press play → time advances.

**Phase 1 done when:** a single process (Python or Docker, no other services) serves the page,
and pressing play visibly advances simulated time with working speed/interval/pause controls.

### Phase 2 — pub/sub, persistence, observability

1. **NATS transport** — `TickTransport` interface + JetStream implementation; publish loop with
   deadline; stream/consumer setup; docker-compose NATS service.
2. **Tick contract + run/reset semantics** — message schema, `run_id` minting on reset, frozen
   ticks while paused, trace-context headers.
3. **Persistence for reliability** — restore/persist clock state so a restart resumes the run.
4. **Observability** — structured logs, Prometheus metrics, optional OTLP traces with header
   propagation.
5. **Demo wiring** — compose simulator + NATS (+ aircraft + ADS-B as they land); a documented
   example that starts a flight, pauses it, and accelerates it to arrival; update the main repo's
   `scripts/demo.sh`.

Full milestone success (per the goals) is met when a locally runnable simulator advances absolute
simulated time, publishes ticks a single aircraft consumes to fly MSP→ORD, honors live
pause/resume/speed/reset, survives a restart, makes delivery/keep-up visible, and ships a
documented start→pause→accelerate example.

## Open items

- Confirm broker choice (NATS JetStream recommended; Redis Streams / Kafka are alternatives).
- Confirm the final tick subject/stream names and whether the fleet shares one subject (current
  plan) or partitions per run/aircraft as it grows.
- Coordinate the tick message schema with the aircraft service once its source exists (the old
  `POST /tick` snapshot contract in the main repo's ARCHITECTURE.md is superseded by this design).
