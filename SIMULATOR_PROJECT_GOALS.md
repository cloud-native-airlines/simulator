# Cloud Native Airlines Simulator Project Goals

## Purpose

The Simulator gives Cloud Native Airlines a controllable simulated world. It owns the passage of time and tells aircraft when to update, allowing a flight to unfold at normal speed, finish in a few minutes, or pause during a demonstration.

Cloud Native Airlines is an observability demo built around an airline. Aircraft will run as individual Kubernetes pods, fly scheduled routes, and report simulated transponder data. A flight tracker shows their movement, and an airport display shows departures and arrivals. The goal is to connect visible behavior to the software and infrastructure producing it, so someone can investigate why an aircraft stopped reporting or why a service fell behind.

The Simulator's first job is to make that world run predictably. Later, it can introduce weather, passenger demand, and economic conditions that affect airline operations.

## Initial scope

The first version controls one aircraft flying a fixed route from Minneapolis to Chicago O'Hare. It provides controls to start, pause, resume, change speed, and reset the simulation. At a configurable interval, it delivers a tick containing the current simulated time to the aircraft.

The aircraft calculates its own position, altitude, speed, heading, and flight status. It sends position reports to ADS-B, which stores them and makes them available for queries. This creates a small, complete demonstration: start the clock, watch reports change, pause the clock, and accelerate the flight to arrival.

## Time model

The Simulator keeps simulated time separate from real time. Flight plans use simulated time; HTTP latency, database write duration, and reporting outages are measured in real time.

| Control | Meaning | Example |
| --- | --- | --- |
| Simulated time | Current timestamp in the airline's world | 14:30 UTC on the scenario date |
| Clock speed | Simulated seconds advanced per real second | At 60 times speed, one real second advances one simulated minute |
| Tick interval | Real time between update deliveries | One tick every real second |
| Pause | Stop simulated time advancing | Aircraft remain at the same point in their flight |
| Reset | Start a new run at the scenario's starting time | Replay the same schedule with a new run ID |

Clock speed and tick interval are independent. Increasing speed changes how fast flights progress. Shortening the tick interval increases reporting frequency. This allows the demo to explore both aircraft behavior and software load.

Pausing freezes simulated movement. Whether the service continues sending unchanged-time ticks while paused is an implementation choice that should be documented, since it affects reporting freshness on the map.

## Tick delivery

Each tick identifies its simulation run, its sequence number, and an absolute simulated timestamp. Aircraft use that timestamp and their flight plan to calculate state. They should not advance a fixed distance merely because another request arrived: duplicated requests must not move a plane twice, and a missed tick must not leave it permanently behind.

Tick delivery should use bounded concurrency and request deadlines. One unreachable aircraft must not prevent updates to the rest of the fleet. The Simulator records delivery failures and continues advancing the world; aircraft can catch up on a later tick.

Resetting creates a new run ID so reports from different runs remain distinguishable. The first version can use configured aircraft endpoints and static flight plans. Discovery and more sophisticated lifecycle management can follow as the fleet grows.

## Component boundaries

| Component | Responsibility |
| --- | --- |
| Simulator | Clock, speed, tick interval, run identity, and delivery of updates |
| Aircraft | Execute assigned flight plans and calculate physical state |
| ADS-B | Receive and store position reports; expose latest positions and flight history |
| Operations | Own fleet records, routes, schedules, assignments, and operational flight status |
| Flight Tracker | Display aircraft positions and reporting freshness |
| FIDS | Display departures and arrivals for a configured airport |

The main `cloud-native-airlines` repository packages these components, supplies example scenarios, and documents how to run the demo. The proposed implementation language for Simulator is Python with FastAPI, leaving room for future demand and economy models.

## Observability goals

The Simulator should help an operator answer three questions: Is simulated time advancing as intended? Are aircraft receiving updates? Can the service keep up with the configured fleet and tick rate?

Useful measurements include tick processing duration, real elapsed time between ticks, delivery successes and failures, aircraft request latency, and pending work. Structured logs identify the run, tick, and aircraft involved. Distributed traces connect tick delivery to aircraft processing and downstream reporting where those paths are instrumented.

Demonstrations should expose visible consequences. An unreachable aircraft stops producing fresh positions while other flights continue. A slow aircraft endpoint raises delivery latency. A faster tick rate or larger fleet increases load and reveals bottlenecks. These scenarios let viewers connect the map to traces, logs, metrics, and Kubernetes behavior.

## First milestone success criteria

- A locally runnable Simulator delivers ticks to one aircraft without requiring Kubernetes or Operations.
- The aircraft progresses from departure to arrival using absolute simulated time.
- Pause and resume preserve simulated time, and changing speed does not make the clock jump backward.
- Clock speed and tick interval can be configured independently.
- Reset begins a distinct run at the configured starting time.
- Failed deliveries are visible and do not stall the simulation indefinitely.
- Logs and basic telemetry explain clock advancement and tick delivery.
- A documented example shows how to start a flight, pause it, and accelerate it to arrival.

## Future development

After the clock and delivery loop work, expand to multiple aircraft and schedules, then add reproducible scenarios with seeded randomness. Weather can introduce delays or operating restrictions. Passenger demand and an economy model can generate booking activity and route popularity. Operations remains responsible for scheduling and business decisions; the Simulator supplies the evolving conditions that influence them.

The priority is a sequence of useful, observable demonstrations. Each addition should create behavior people can see and explain through telemetry.
