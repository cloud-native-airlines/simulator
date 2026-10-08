from datetime import datetime, timezone

from fastapi.testclient import TestClient

from simulator.app import create_app
from simulator.config import Config


def make_client() -> TestClient:
    config = Config(
        run_id="run-test",
        start_time=datetime(2026, 10, 6, 14, 0, 0, tzinfo=timezone.utc),
        clock_speed=60.0,
        tick_interval=1.0,
        start_paused=True,
        scenario_path=None,
        host="127.0.0.1",
        port=8000,
    )
    return TestClient(create_app(config))


def test_health_and_ready():
    with make_client() as client:
        assert client.get("/healthz").json() == {"status": "ok"}
        assert client.get("/readyz").json() == {"status": "ready"}


def test_clock_snapshot_shape():
    with make_client() as client:
        body = client.get("/clock").json()
        assert body["run_id"] == "run-test"
        assert body["paused"] is True
        assert set(body) == {
            "run_id", "simulated_at", "real_time", "tick_id",
            "speed", "tick_interval", "paused",
        }


def test_pause_resume_and_patch():
    with make_client() as client:
        assert client.post("/control/resume").json()["paused"] is False
        assert client.post("/control/pause").json()["paused"] is True

        patched = client.patch("/clock", json={"speed": 120, "tick_interval": 0.5}).json()
        assert patched["speed"] == 120.0
        assert patched["tick_interval"] == 0.5

        # Empty patch is rejected.
        assert client.patch("/clock", json={}).status_code == 400
        # Non-positive values rejected by the schema.
        assert client.patch("/clock", json={"speed": 0}).status_code == 422


def test_reset_mints_new_run_id():
    with make_client() as client:
        original = client.get("/clock").json()["run_id"]
        reset = client.post("/control/reset").json()
        assert reset["run_id"] != original
        assert reset["tick_id"] == 0


def test_index_served():
    with make_client() as client:
        res = client.get("/")
        assert res.status_code == 200
        assert "CNA Simulator" in res.text
