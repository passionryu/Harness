from agents.base import AgentRunner
from agents.dev_agent import DevAgent
from agents.plan_agent import PlanAgent
from agents.qa_agent import QAAgent


class AgentRegistry:
    def __init__(self) -> None:
        self._agents: dict[str, AgentRunner] = {
            "plan": PlanAgent(),
            "dev": DevAgent(),
            "qa": QAAgent(),
        }

    def get(self, name: str) -> AgentRunner:
        agent = self._agents.get(name)
        if agent is None:
            raise ValueError(f"알 수 없는 Agent입니다: {name}")
        return agent
