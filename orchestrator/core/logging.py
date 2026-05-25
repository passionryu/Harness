import logging
import sys

from pythonjsonlogger import json


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level.upper())

    handler = logging.StreamHandler(sys.stdout)
    formatter = json.JsonFormatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s %(task_id)s %(run_id)s %(agent_name)s"
    )
    handler.setFormatter(formatter)
    root.addHandler(handler)
