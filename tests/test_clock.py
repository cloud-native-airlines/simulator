from datetime import datetime, timezone

import pytest

from simulator.clock import Clock, to_rfc3339


class FakeMono:
    """A controllable monotonic clock for deterministic advancement tests."""

    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


START = datetime(2026, 10, 6, 14, 0, 0, tzinfo=timezone.utc)


def make_clock(mono: FakeMono, *, speed=60.0, interval=1.0, paused=False) -> Clock:
    return Clock(
        run_id="run-1",
        start_time=START,
        speed=speed,
        tick_interval=interval,
        start_paused=paused,
        monotonic=mono,
    )


def test_observable_time_steps_only_at_ticks():
    mono = FakeMono()
    clock = make_clock(mono, speed=60.0)
    # Before the first tick the observable time sits at the start.
    assert clock.simulated_at == START
    mono.advance(0.5)  # half a real second elapses, but no tick fired
    assert clock.simulated_at == START  # does NOT drift between ticks
    mono.advance(0.5)  # one full real second total
    clock.advance_tick()
    # 60x: one real second => a single 60-simulated-second step.
    assert clock.simulated_at == START.replace(minute=1)


def test_advances_by_speed():
    mono = FakeMono()
    clock = make_clock(mono, speed=60.0)
    mono.advance(1.0)  # one real second
    clock.advance_tick()
    # 60x: one real second => 60 simulated seconds.
    assert clock.simulated_at == START.replace(minute=1)


def test_pause_freezes_time():
    mono = FakeMono()
    clock = make_clock(mono, speed=60.0)
    mono.advance(2.0)
    clock.advance_tick()
    clock.pause()
    frozen = clock.simulated_at
    mono.advance(100.0)  # real time passes while paused
    clock.advance_tick()  # a tick while paused samples the frozen clock
    assert clock.simulated_at == frozen


def test_resume_does_not_jump():
    mono = FakeMono()
    clock = make_clock(mono, speed=60.0)
    mono.advance(2.0)
    clock.advance_tick()
    clock.pause()
    before = clock.simulated_at
    mono.advance(100.0)  # paused gap must not count
    clock.resume()
    clock.advance_tick()
    assert clock.simulated_at == before  # no jump across the paused gap
    mono.advance(1.0)
    clock.advance_tick()
    assert clock.simulated_at == before.replace(second=0, minute=before.minute + 1)


def test_speed_change_no_backward_jump():
    mono = FakeMono()
    clock = make_clock(mono, speed=60.0)
    mono.advance(1.0)
    clock.advance_tick()
    at_change = clock.simulated_at  # == 14:01:00
    clock.set_speed(1.0)
    # Changing speed must not move the clock at the instant of change.
    assert clock._compute_now() == at_change
    mono.advance(10.0)  # now advancing at 1x
    clock.advance_tick()
    assert clock.simulated_at == at_change.replace(second=10)


def test_tick_interval_independent_of_speed():
    mono = FakeMono()
    clock = make_clock(mono, speed=60.0, interval=1.0)
    clock.set_tick_interval(0.25)
    assert clock.tick_interval == 0.25
    assert clock.speed == 60.0  # unchanged
    mono.advance(1.0)
    clock.advance_tick()
    assert clock.simulated_at == START.replace(minute=1)  # speed still drives time


def test_reset_starts_new_run_at_start_time():
    mono = FakeMono()
    clock = make_clock(mono, speed=60.0, paused=False)
    mono.advance(5.0)
    clock.advance_tick()
    assert clock.tick_id == 1
    clock.reset("run-2")
    assert clock.run_id == "run-2"
    assert clock.tick_id == 0
    assert clock.simulated_at == START
    assert clock.paused is False  # start_paused was False


def test_reset_restores_start_paused():
    mono = FakeMono()
    clock = make_clock(mono, paused=True)
    clock.resume()
    assert clock.paused is False
    clock.reset("run-2")
    assert clock.paused is True


def test_default_start_is_now_when_unspecified():
    # The resolution lives in config.load_config; here we just confirm the
    # clock faithfully reports whatever start it was given.
    mono = FakeMono()
    now = datetime.now(timezone.utc)
    clock = Clock(run_id="r", start_time=now, speed=1.0, tick_interval=1.0,
                  start_paused=True, monotonic=mono)
    assert clock.simulated_at == now


def test_rejects_bad_values():
    mono = FakeMono()
    with pytest.raises(ValueError):
        make_clock(mono, speed=0.0)
    clock = make_clock(mono)
    with pytest.raises(ValueError):
        clock.set_speed(-1.0)
    with pytest.raises(ValueError):
        clock.set_tick_interval(0.0)


def test_to_rfc3339_uses_z_suffix():
    assert to_rfc3339(START).startswith("2026-10-06T14:00:00")
    assert to_rfc3339(START).endswith("Z")
