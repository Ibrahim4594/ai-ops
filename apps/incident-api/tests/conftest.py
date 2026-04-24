import os
from pathlib import Path

import pytest

os.environ.setdefault("DISABLE_OTEL", "1")


@pytest.fixture(autouse=True)
def test_env(tmp_path: Path):
    os.environ["DISABLE_OTEL"] = "1"
    os.environ["INCIDENT_DB_PATH"] = str(tmp_path / "incidents.db")
    os.environ["INCIDENT_ARTIFACT_DIR"] = str(tmp_path / "artifacts")
    os.environ["INCIDENT_WORKER_INTERVAL_SECONDS"] = "0.05"
    os.environ.pop("INCIDENT_ACTION_FAIL_ON_SEVERITY", None)
    yield
