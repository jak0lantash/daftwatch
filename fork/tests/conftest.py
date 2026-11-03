import os

import pytest

FORK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(autouse=True)
def app_env(tmp_path, monkeypatch):
    monkeypatch.setenv("FORK_DIR", FORK)
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("DEBUG_DIR", str(tmp_path / "debug"))
    for k in ("CENTRE_LAT", "CENTRE_LNG", "CENTRE_NAME"):
        monkeypatch.delenv(k, raising=False)
    from adwatch import config, db, fetcher, sites
    monkeypatch.setattr(fetcher, "DEBUG_DIR", str(tmp_path / "debug"))
    monkeypatch.setattr("adwatch.throttle.wait_turn", lambda *a, **k: None)  # no 20 s gaps in tests
    config.reset(); sites.reset(); db.close(); fetcher._workers.clear()
    yield tmp_path
    db.close(); config.reset(); sites.reset(); fetcher._workers.clear()
