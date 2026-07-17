import sys

import orchestrator.api.routes as routes
import orchestrator.services.orchestration as orchestration
from orchestrator.core.logging import configure_logging


def pytest_runtest_setup(item):
    configure_logging("CRITICAL", stream=sys.stderr)
    orchestration.settings.allow_external_notifications = False
    routes.settings.enable_github_comment_commands = True
