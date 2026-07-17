# CLI Usage Guide

## 기본 원칙

`harness` CLI는 Codex가 읽을 artifact를 만드는 도구다.
DB 상태 전이, 장기 실행 작업, 자동 앱 구현은 하지 않는다.

## 준비

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
pytest
```

`.env`에는 GitHub, Notion, Discord, target repo 경로처럼 실제 도구 호출에 필요한 값만 둔다.

## 자주 쓰는 명령

```bash
harness agent-specs
harness playbooks
harness sync --issue 13
harness design --issue 13
harness develop --issue 13
harness qa --issue 13
harness approve --issue 13 --stage qa --approved-by rsy
harness document --issue 13
harness status --issue 13
```

## 작업 흐름

1. `sync`로 GitHub issue context artifact를 만든다.
2. `design`으로 개발 가능한 설계 artifact를 만든다.
3. `develop`으로 Codex 구현 요청과 커밋 계획을 만든다.
4. Codex가 target repo에서 실제 구현, 테스트, 커밋, 푸시를 수행한다.
5. `qa`로 이슈 맞춤 QA Plan과 보고서 초안을 만든다.
6. Codex가 실제 검증을 수행하고 결과를 보고서에 반영한다.
7. 사람이 확인한 뒤 `approve`로 승인 기록 artifact를 남긴다.
8. 필요하면 `document` 또는 `domain-knowledge`를 실행한다.

## Deprecated Alias

`plan`은 `design`의 deprecated alias다.
새 작업에서는 `harness design --issue <number>`를 사용한다.

`fix-develop`은 새 복구를 수행하지 않는다.
Codex가 issue와 artifact를 읽고 직접 수정해야 한다.

## auto-run

```bash
harness auto-run --issue 13 --until qa
```

`auto-run`은 design/develop/qa artifact를 순서대로 생성할 뿐이다.
실제 구현과 검증은 Codex가 별도로 수행한다.
