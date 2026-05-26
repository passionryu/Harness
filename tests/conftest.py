import os
from pathlib import Path

TEST_DB_PATH = Path(__file__).resolve().parents[1] / "ai_harness_test.db"
TEST_DB_PATH.unlink(missing_ok=True)
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH}"

import orchestrator.services.orchestration as orchestration  # noqa: E402


def pytest_runtest_setup(item):
    orchestration.settings.allow_external_notifications = False
