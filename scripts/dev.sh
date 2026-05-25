#!/usr/bin/env bash
set -euo pipefail

uvicorn orchestrator.main:app --reload --host 0.0.0.0 --port 8080

