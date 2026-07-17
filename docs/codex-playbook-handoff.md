# Codex Playbook Handoff

## 목적

하네스의 에이전트 동작을 Python 코드 중심에서 Markdown playbook 중심으로 옮긴다.
사용자는 Python을 몰라도 에이전트의 역할, 호출 조건, 판단 기준, 보고서 형식을 읽고 수정할 수 있어야 한다.

## 운영 원칙

- 역할, 판단 기준, 실행 단계, 금지 사항은 Markdown이 원본이다.
- Codex가 Markdown playbook을 읽고 실제 구현, 검증, 문서화를 수행한다.
- Python은 GitHub/Notion/Discord 호출, artifact 저장, CLI/webhook adapter 같은 도구 호출만 담당한다.
- 새 자동화가 필요하면 먼저 Markdown spec/playbook을 고친다.
- 반복 가능한 외부 도구 호출만 Python adapter로 만든다.

## 디렉토리

```text
agents/specs/       에이전트 역할과 호출 기준
agents/playbooks/   Codex가 실제 작업 때 따르는 실행 지침
artifacts/          Issue별 context, handoff, QA, approval 기록
```

## 조회 명령

```bash
harness agent-specs
harness agent-specs --name qa
harness playbooks
harness playbooks --name frontend-implementation
```

## 수정 기준

에이전트의 역할이나 호출 조건을 바꾸려면 `agents/specs/<agent>.md`를 수정한다.

실제 구현·검증 절차를 바꾸려면 `agents/playbooks/<name>.md`를 수정한다.

Python 수정은 다음 경우로 제한한다.

- GitHub, Discord, Notion API 호출
- branch checkout, commit, push 같은 실제 도구 호출
- 테스트 명령 실행과 timeout 처리
- Playwright 실행과 screenshot 저장
- PDF 렌더링
- schema validation

## 라우팅 기준

| 작업 성격 | 우선 playbook | 금지할 오라우팅 |
| --- | --- | --- |
| FE 화면/폼/상태 | `frontend-implementation` | 백엔드 설계 기준으로 구현 지시 |
| Kotlin Spring BE | `backend-kotlin-spring` | 프론트엔드 화면 기준으로 구현 지시 |
| FE/BE 연동 | `api-connect` | 무관한 회원가입 smoke로 QA 통과 처리 |
| QA | `qa-verification` | 고정 checklist만으로 PASS 처리 |
| infra/config | `infra-config` | 도메인 모델링 기준으로 설정 변경 지시 |
| 문서화 | `documentation` | 전체 로그 복붙 |

## 완료 기준

- 모든 spec/playbook은 frontmatter를 가진다.
- 모든 playbook은 `Mission`, `Codex Execution Steps`, `Decision Rules`, `Hard Rules`를 가진다.
- Dev Agent는 선택한 playbook과 Codex 실행 요청 artifact를 남긴다.
- QA Agent는 기획/설계안 기반의 QA Plan과 Human QA 체크리스트를 남긴다.
- 자동 검증하지 않은 항목은 pass로 표시하지 않는다.
