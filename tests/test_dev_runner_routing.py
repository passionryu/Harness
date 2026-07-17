from agents.dev_agent import _codex_playbooks


def test_frontend_bugfix_uses_frontend_playbook_without_python_implementation_layer():
    playbooks = _codex_playbooks(
        "bugfix",
        "[Bugfix] 설정 색상 선택이 화면 테마에 반영되지 않음",
        "프론트엔드 설정 화면 색상과 localStorage 문제를 수정한다.",
    )

    assert playbooks == ["frontend-implementation"]


def test_backend_issue_uses_backend_playbook_without_python_implementation_layer():
    playbooks = _codex_playbooks(
        "beFeature",
        "[BE] 회원가입 API 구현",
        "Kotlin Spring API와 DB 저장을 구현한다.",
    )

    assert playbooks == ["backend-kotlin-spring"]
