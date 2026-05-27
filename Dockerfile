FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends git docker.io \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY orchestrator ./orchestrator
COPY agents ./agents
COPY workflows ./workflows
COPY sandbox ./sandbox
COPY mcp ./mcp
COPY memory ./memory
COPY prompts ./prompts
COPY rules ./rules

RUN pip install --no-cache-dir -e .

EXPOSE 3002

CMD ["uvicorn", "orchestrator.main:app", "--host", "0.0.0.0", "--port", "3002"]
