import orchestrator.services.orchestration as orchestration


def pytest_runtest_setup(item):
    orchestration.settings.allow_external_notifications = False
