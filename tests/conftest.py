import os
import sys
from pathlib import Path

TEST_DB_PATH = Path(__file__).resolve().parents[1] / "ai_harness_test.db"
TEST_DB_PATH.unlink(missing_ok=True)
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH}"

import orchestrator.services.orchestration as orchestration  # noqa: E402
import orchestrator.api.routes as routes  # noqa: E402
from orchestrator.core.logging import configure_logging  # noqa: E402


def pytest_runtest_setup(item):
    configure_logging("CRITICAL", stream=sys.stderr)
    orchestration.settings.allow_external_notifications = False
    routes.settings.enable_github_comment_commands = True
