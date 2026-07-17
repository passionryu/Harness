from pydantic import BaseModel


class HumanApproval(BaseModel):
    approved_by: str
    notes: str = ""


class EventResult(BaseModel):
    task_id: str
    previous_state: str
    current_state: str
    message: str
