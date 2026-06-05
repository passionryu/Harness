from agents.base import AgentRunner
from agents.dev_agent import DevAgent
from agents.domain_knowledge_agent import DomainKnowledgeAgent
from agents.documentation_agent import DocumentationAgent
from agents.plan_agent import PlanAgent
from agents.qa_agent import QAAgent
from agents.review_agent import ReviewAgent


class AgentRegistry:
    def __init__(self) -> None:
        self._agents: dict[str, AgentRunner] = {
            "plan": PlanAgent(),
            "dev": DevAgent(),
            "review": ReviewAgent(),
            "qa": QAAgent(),
            "documentation": DocumentationAgent(),
            "domain_knowledge": DomainKnowledgeAgent(),
        }

    def get(self, name: str) -> AgentRunner:
        agent = self._agents.get(name)
        if agent is None:
            raise ValueError(f"알 수 없는 Agent입니다: {name}")
        return agent
