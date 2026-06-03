from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "ai-harness"
    app_env: str = "local"
    log_level: str = "INFO"
    database_url: str = "sqlite:///./ai_harness.db"
    artifact_root: Path = Path("artifacts")
    target_repo_path: Path = Path("../studyHub")
    agent_timeout_seconds: int = 900
    agent_retry_limit: int = 2
    openai_api_key: str | None = None
    github_owner: str = "passionryu"
    github_repo: str = "studyHub"
    github_token: str | None = None
    github_use_gh_cli: bool = False
    github_webhook_secret: str | None = None
    enable_github_comment_commands: bool = False
    plan_trigger_label: str = "ai-plan-ready"
    plan_command: str = "@ai-harness plan"
    replan_command: str = "@ai-harness replan"
    develop_command: str = "@ai-harness develop"
    fix_develop_command: str = "@ai-harness fix-develop"
    refactor_command: str = "@ai-harness refactor"
    qa_command: str = "@ai-harness qa"
    reqa_command: str = "@ai-harness re-qa"
    status_command: str = "@ai-harness status"
    cancel_command: str = "@ai-harness cancel"
    allow_external_notifications: bool = False
    google_chat_webhook_url: str | None = None
    discord_webhook_url: str | None = None
    frontend_base_url: str = "http://localhost:3000"
    studyhub_api_base_url: str = "http://localhost:3001"
    studyhub_swagger_url: str = "http://localhost:3001/swagger-ui/index.html"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
