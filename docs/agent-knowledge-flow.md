# Planning Assistant Agent와 Domain Knowledge Agent

## 목적

이 문서는 기획 지원과 도메인 지식 정리 흐름을 설명한다.
두 Agent는 구현을 직접 수행하지 않고, 사람이 더 좋은 결정을 하도록 지식과 맥락을 정리한다.

## Planning Assistant Agent

### 역할

Planning Assistant Agent는 이슈를 만들기 전 단계에서 동작한다.
Obsidian Vault의 리서치, 기획 메모, 구현된 기능 기록을 읽고 다음 기능 후보와 질문을 만든다.

### 입력

- Obsidian Vault 경로
- 사용자가 입력한 기획 주제
- 추가 요청 메모
- `research/`, `planning/`, `references/`, `agent-context/` 문서

### 출력

- 기획 보고서 artifact
- GitHub Issue 초안 artifact
- Obsidian `planning/planning-assistant-suggestions.md` 누적 기록

### 동작 원리

1. `agent-context/planning-assistant-context.md`에서 서비스 맥락을 읽는다.
2. `agent-context/implemented-features.md`에서 이미 구현된 기능을 확인한다.
3. `planning/user-problems.md`, `planning/feature-ideas.md`, `research/mental-care-apps.md`를 참고한다.
4. 다음 기능 후보, 확인 질문, 위험 요소를 정리한다.
5. 사람이 검토할 수 있는 GitHub Issue 초안을 만든다.

### 사용 방법

```bash
cd /Users/rsy/Desktop/myPlayGround/harness

.venv/bin/python -m ai_harness.cli planning-assist \
  --topic "감정 기록 기능" \
  --note "부담 없는 기록 흐름을 기획하고 싶다."
```

## Domain Knowledge Agent

### 역할

Domain Knowledge Agent는 QA가 끝난 구현 결과를 Obsidian에 서비스 지식으로 정리한다.
Notion이 작업 일지라면, Obsidian은 서비스 도메인 지식과 기획 보조 Agent의 참고 자료다.

### 입력

- GitHub Issue 정보
- Plan/Dev/QA 산출물
- Obsidian Vault 경로

### 출력

- `agent-context/implemented-features.md`
- `agent-context/planning-assistant-context.md`
- `planning/domain-decisions.md`
- Domain Knowledge artifact

### 동작 원리

1. Plan 산출물에서 서비스 지식과 정책을 읽는다.
2. Dev 산출물에서 실제 구현된 동작을 읽는다.
3. QA 산출물에서 검증된 결과를 읽는다.
4. 구현된 기능과 도메인 결정을 Obsidian에 정리한다.
5. 같은 이슈를 다시 정리하면 기존 section을 교체해 중복 기록을 줄인다.

### 사용 방법

```bash
cd /Users/rsy/Desktop/myPlayGround/harness

.venv/bin/python -m ai_harness.cli domain-knowledge --issue <이슈번호>
```

## 운영 원칙

- Planning Assistant Agent는 GitHub Issue를 자동 생성하지 않는다.
- Domain Knowledge Agent는 Human QA 이후 사람이 필요하다고 판단할 때 수동 호출한다.
- 확정되지 않은 기획은 Obsidian에 남기고, 확정된 구현 작업만 GitHub Issue로 이동한다.
- 사용자에게 공개할 수 있는 공식 서비스 지식은 프로젝트 `docs/`로 옮긴다.

