from datetime import datetime

from pydantic import BaseModel, Field


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    body: str = ""
    github_issue_url: str | None = None
    github_issue_number: int | None = None


class TaskRead(BaseModel):
    id: str
    title: str
    body: str
    state: str
    retry_count: int
    retry_limit: int
    human_approved_at: datetime | None

    model_config = {"from_attributes": True}


class ManualEvent(BaseModel):
    task_id: str
    event: str = Field(
        description="triage, start_dev, dev_complete, qa_pass, qa_fail, human_reject"
    )
    reason: str = ""


class HumanApproval(BaseModel):
    approved_by: str
    notes: str = ""


class EventResult(BaseModel):
    task_id: str
    previous_state: str
    current_state: str
    message: str

