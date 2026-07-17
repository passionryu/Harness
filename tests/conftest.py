import sys

import orchestrator.api.routes as routes
import orchestrator.services.orchestration as orchestration
from orchestrator.core.logging import configure_logging


def pytest_runtest_setup(item):
    configure_logging("CRITICAL", stream=sys.stderr)
    orchestration.settings.allow_external_notifications = False
    orchestration.settings.github_token = None
    orchestration.settings.github_use_gh_cli = False
    orchestration.settings.github_project_number = None
    routes.settings.enable_github_comment_commands = True
    routes.settings.github_token = None
    routes.settings.github_use_gh_cli = False
    routes.settings.github_project_number = None
