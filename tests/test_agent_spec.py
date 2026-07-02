from pathlib import Path

import pytest

from agents.agent_spec import AgentSpecError, parse_agent_spec, render_agent_spec_context


def test_parse_agent_spec_reads_frontmatter_and_required_sections():
    spec = parse_agent_spec(
        """---
name: qa
version: 1
summary: 기획과 설계안을 기준으로 QA Plan을 만든다.
triggers:
  - "@ai-harness qa"
inputs:
  - github_issue
  - design_artifacts
outputs:
  - qa-plan.md
  - qa-report.md
---
# Mission
이번 작업 전용 검증 기준을 만든다.

# Decision Rules
- 이슈의 QA 기준을 고정 체크리스트보다 우선한다.

# Hard Rules
- 자동 검증하지 못한 항목은 PASS로 표시하지 않는다.
""",
        path=Path("qa.md"),
    )

    assert spec.name == "qa"
    assert spec.version == 1
    assert spec.triggers == ["@ai-harness qa"]
    assert spec.inputs == ["github_issue", "design_artifacts"]
    assert spec.outputs == ["qa-plan.md", "qa-report.md"]
    assert "이번 작업 전용" in spec.section("Mission")

    rendered = "\n".join(render_agent_spec_context(spec))
    assert "Agent Markdown Spec: qa" in rendered
    assert "자동 검증하지 못한 항목" in rendered


def test_parse_agent_spec_rejects_missing_required_sections():
    with pytest.raises(AgentSpecError, match="필수 섹션"):
        parse_agent_spec(
            """---
name: qa
version: 1
summary: QA Agent
triggers: ["@ai-harness qa"]
inputs: [github_issue]
outputs: [qa-report.md]
---
# Mission
검증한다.
""",
            path=Path("qa.md"),
        )
