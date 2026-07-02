# Codex Playbook Runner Reform

## 목적

하네스의 에이전트 동작을 Python 코드 중심에서 Markdown playbook 중심으로 옮긴다.
사용자는 Python을 직접 읽지 않아도 에이전트가 언제 호출되고, 어떤 순서로 판단하고, 무엇을 검증해야 하는지 수정할 수 있어야 한다.

## 새 원칙

- 역할, 판단 기준, 실행 단계, 금지 사항은 Markdown이 원본이다.
- Codex가 Markdown playbook을 읽고 실제 구현, 검증, 보고를 수행한다.
- Python은 상태 전이, 외부 API, artifact 저장, 테스트 실행, PDF 렌더링 같은 부작용 있는 작업을 담당한다.
- 새 자동화가 필요하면 먼저 Markdown playbook을 만들고, 반복 실행이 필요한 부분만 얇은 Python adapter로 만든다.

## 디렉토리

```text
agents/specs/       에이전트 역할과 호출 기준
agents/playbooks/   Codex가 실제 구현/검증 때 따르는 실행 지침
agents/runners/     기존 Python runner 호환층
```

## 조회 명령

```bash
harness agent-specs
harness agent-specs --name qa
harness playbooks
harness playbooks --name frontend-implementation
```

## 작업자가 수정해야 하는 곳

### 에이전트 역할을 바꾸고 싶을 때

`agents/specs/<agent>.md`를 수정한다.

예시:

- Dev Agent의 호출 조건
- QA Agent의 보고서 형식
- Documentation Agent의 Notion 정리 기준
- UI/UX Designer Agent의 Planning handoff 기준

### 실제 구현 절차를 바꾸고 싶을 때

`agents/playbooks/<name>.md`를 수정한다.

예시:

- FE 작업에서 어떤 테스트를 우선 실행할지
- BE 작업에서 DDD 경계를 어떻게 확인할지
- QA 보고서에서 캡처를 어떤 순서로 설명할지
- infra/config 작업을 어떤 검증 순서로 처리할지

### Python을 수정해야 하는 경우

다음처럼 실제 부작용이 있거나 반복 실행이 필요한 경우에만 Python을 수정한다.

- GitHub, Discord, Notion API 호출
- DB state transition
- branch checkout, commit, push
- 테스트 명령 실행과 timeout 처리
- Playwright 실행과 screenshot 저장
- PDF 렌더링
- schema validation

## 기존 Python Runner의 위치

`agents/runners/*.py`는 당장 삭제하지 않는다.
현재 auto-run, QA PDF, branch guard, artifact 저장과 연결되어 있기 때문이다.

다만 새 기능의 판단 기준은 Python runner 내부 조건문이 아니라 Markdown playbook에 먼저 추가한다.
Python runner는 다음 역할로 격하한다.

- repeatable command adapter
- evidence collector
- safety guard

## 라우팅 기준

| 작업 성격 | 우선 playbook | 금지할 오라우팅 |
| --- | --- | --- |
| FE 화면/폼/상태 | `frontend-implementation` | DDD Modeling Runner |
| Kotlin Spring BE | `backend-kotlin-spring` | Frontend Implementation Runner |
| FE/BE 연동 | `api-connect` | 무관한 회원가입 smoke |
| QA | `qa-verification` | 고정 checklist만으로 PASS |
| infra/config | `infra-config` | DDD Modeling Runner |
| 문서화 | `documentation` | 전체 로그 복붙 |

## 완료 기준

- 모든 playbook은 frontmatter를 가진다.
- 모든 playbook은 `Mission`, `Codex Execution Steps`, `Decision Rules`, `Hard Rules`를 가진다.
- `pytest tests/test_agent_spec.py tests/test_cli.py`가 통과해야 한다.
- 새 runner Python 코드를 추가했다면 왜 Markdown만으로 부족했는지 문서에 남긴다.

## 다음 개혁 단계

1. Dev Agent가 산출물에 선택한 playbook 이름과 handoff를 항상 남기게 한다.
2. QA Agent가 PDF 보고서 첫 장에 QA playbook과 QA Plan 출처를 표시하게 한다.
3. 기존 `agents/runners/responsibility_runners.py`의 큰 조건문을 playbook 이름 기준의 얇은 adapter로 분해한다.
4. 충분히 대체된 Python runner는 deprecated 표시 후 제거한다.
