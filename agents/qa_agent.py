import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from git import Repo

from agents.base import AgentInput, AgentResult, AgentStatus, ArtifactSpec
from orchestrator.core.settings import settings

FE_HUMAN_QA_CHECKLIST = [
    "브라우저에서 메인 화면에 접속했을 때 회원가입 진입 버튼 또는 링크가 보이는가",
    "회원가입 진입 버튼을 클릭하면 `/signup` 화면으로 정상 이동하는가",
    "이름, 이메일, 비밀번호, 전화번호, 관심 영역 입력 필드가 의도한 순서와 형태로 보이는가",
    "모바일/데스크톱 화면에서 폼 레이아웃이 깨지거나 텍스트가 겹치지 않는가",
    "필수 입력값을 비웠을 때 사용자가 이해할 수 있는 검증 메시지가 보이는가",
    "잘못된 이메일 또는 너무 짧은 비밀번호 입력 시 제출이 막히는가",
    "정상 입력 후 제출했을 때 현재 단계에 맞는 안내 또는 mock-safe 동작이 보이는가",
    "로그인/메인 화면으로 돌아가는 흐름이 어색하지 않은가",
]

BE_HUMAN_QA_CHECKLIST = [
    "Swagger UI에서 회원가입 API의 summary와 description이 한국어로 보이는가",
    "해피케이스 curl 결과가 의도대로 2xx 응답을 반환하는가",
    "중복 이메일, 잘못된 이메일, 짧은 비밀번호 같은 최소 엣지 케이스가 의도한 오류 응답을 반환하는가",
    "API 오류 메시지가 사용자에게 안전하고 이해 가능한 한국어로 반환되는가",
    "회원가입 성공 후 DB에 회원과 관심 영역이 의도대로 저장되는가",
    "비밀번호가 평문이 아니라 해싱된 값으로 저장되는가",
]

CONFIG_HUMAN_QA_CHECKLIST = [
    "Spring Security 설정 테스트가 실제로 통과했는가",
    "백엔드 health가 UP으로 반환되는가",
    "Swagger UI에 접근 가능한가",
    "인증 없이 허용해야 하는 API는 정상 접근 가능한가",
    "보호된 API는 인증 없이 접근했을 때 401 Unauthorized를 반환하는가",
    "Redis 컨테이너가 실행 중이며 health에 반영되는가",
]


CHECK_NAME_KO = {
    "target repository exists": "대상 저장소 존재",
    "expected branch is checked out": "예상 브랜치 체크아웃 상태",
    "test:signup script exists": "test:signup 스크립트 존재",
    "test:signup passes": "test:signup 통과",
    "StudyHub API server is reachable": "StudyHub API 서버 응답",
    "backend happy smoke test passes": "백엔드 해피케이스 smoke test 통과",
    "config security test passes": "Config Security 설정 테스트 통과",
    "config backend health is UP": "Config 백엔드 health UP",
    "config swagger is reachable": "Config Swagger 접근 가능",
    "config signup endpoint is permitted": "Config 회원가입 API 인증 없이 접근 가능",
    "config protected api returns 401": "Config 보호 API 미인증 401 반환",
    "config redis container is running": "Config Redis 컨테이너 실행",
}


@dataclass(frozen=True)
class ApiSmokeCase:
    name: str
    path: str
    request_json: dict[str, Any]
    expected_status: int


@dataclass(frozen=True)
class ApiSmokeResult:
    name: str
    path: str
    request_json: dict[str, Any]
    response_json: str
    status_code: int | None
    curl_exit_code: int
    passed: bool


@dataclass(frozen=True)
class ConfigQaCheckResult:
    name: str
    passed: bool
    target: str
    expected: str
    actual: str
    detail: str = ""


def _translate_check_name(name: str) -> str:
    if name.startswith("artifact exists: "):
        return f"산출물 존재: {name.removeprefix('artifact exists: ')}"
    if name.startswith("signup file exists: "):
        return f"회원가입 파일 존재: {name.removeprefix('signup file exists: ')}"
    if name.startswith("backend edge smoke test passes: "):
        return f"백엔드 엣지케이스 smoke test 통과: {name.removeprefix('backend edge smoke test passes: ')}"
    return CHECK_NAME_KO.get(name, name)


def _extract_section(markdown: str, heading: str) -> list[str]:
    lines = markdown.splitlines()
    collected: list[str] = []
    in_section = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## ") or stripped.startswith("### "):
            marker = "## " if stripped.startswith("## ") else "### "
            if in_section:
                break
            in_section = stripped.removeprefix(marker).strip() == heading
            continue
        if in_section and stripped:
            collected.append(stripped)
    return collected


def _extract_metadata_value(markdown: str, key: str) -> str | None:
    for line in _extract_section(markdown, "Harness Metadata"):
        prefix = f"- {key}:"
        if line.startswith(prefix):
            return line.removeprefix(prefix).strip()
    return None


def _extract_issue_type(markdown: str) -> str:
    labels = _extract_metadata_value(markdown, "labels") or ""
    for label in [item.strip() for item in labels.split(",")]:
        if label.startswith("type: "):
            return label.removeprefix("type: ").strip()
    return "미지정"


# 이슈 타입에 맞는 QA 대상 브랜치 prefix를 결정한다.
def _branch_prefix(issue_type: str) -> str:
    return {
        "beFeature": "feature(BE)",
        "feFeature": "feature(FE)",
        "fullstackFeature": "feature(FS)",
        "apiConnect": "api-connect",
        "bugfix": "bugfix",
        "hotfix": "hotfix",
        "infra": "infra",
        "config": "config",
        "docs": "docs",
    }.get(issue_type, "task")


def _branch_name(issue_type: str, issue_number: str) -> str:
    number = issue_number if issue_number and issue_number != "unknown" else "no-issue"
    return f"{_branch_prefix(issue_type)}-{number}"


def _run_command(command: list[str], cwd: Path, timeout_seconds: int) -> tuple[int, str, str]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )
    return completed.returncode, completed.stdout, completed.stderr


def _run_background_command(command: list[str], cwd: Path) -> subprocess.Popen[str]:
    return subprocess.Popen(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _package_has_script(package_json: Path, script_name: str) -> bool:
    if not package_json.exists():
        return False
    data = json.loads(package_json.read_text(encoding="utf-8"))
    return script_name in data.get("scripts", {})


def _curl_json(
    method: str,
    url: str,
    payload: dict[str, Any] | None,
    timeout_seconds: int,
) -> tuple[int, str, str, int | None]:
    command = [
        "curl",
        "-sS",
        "-X",
        method,
        "-H",
        "Content-Type: application/json",
        "--max-time",
        str(timeout_seconds),
    ]
    if payload is not None:
        command.extend(["-d", json.dumps(payload, ensure_ascii=False)])
    command.extend(["-w", "\n%{http_code}", url])
    exit_code, stdout, stderr = _run_command(command, Path.cwd(), timeout_seconds + 5)
    status_code: int | None = None
    response_body = stdout
    if stdout:
        response_body, _, status_line = stdout.rpartition("\n")
        try:
            status_code = int(status_line.strip())
        except ValueError:
            status_code = None
    return exit_code, response_body.strip(), stderr.strip(), status_code


def _api_url(path: str) -> str:
    return urljoin(settings.studyhub_api_base_url.rstrip("/") + "/", path.lstrip("/"))


def _health_url() -> str:
    return _api_url("/actuator/health")


def _is_success_status(status_code: int | None) -> bool:
    return status_code is not None and 200 <= status_code < 300


def _is_api_alive() -> bool:
    exit_code, _, _, status_code = _curl_json("GET", _health_url(), None, 5)
    return exit_code == 0 and status_code is not None and 200 <= status_code < 500


def _start_studyhub_api_if_needed(repo_path: Path, timeout_seconds: int) -> tuple[subprocess.Popen[str] | None, str]:
    if _is_api_alive():
        return None, "이미 실행 중인 StudyHub API 서버를 사용했습니다."

    server_root = repo_path / "apps/server"
    if not server_root.exists():
        return None, "StudyHub 서버 디렉토리를 찾지 못했습니다."

    port = settings.studyhub_api_base_url.rsplit(":", 1)[-1].split("/", 1)[0]
    process = _run_background_command(
        [
            "./gradlew",
            ":modules:bootstrap:studyhub:bootRun",
            f"--args=--server.port={port}",
        ],
        server_root,
    )
    deadline = time.time() + min(timeout_seconds, 90)
    while time.time() < deadline:
        if process.poll() is not None:
            stdout, stderr = process.communicate(timeout=5)
            return None, f"StudyHub API 서버 시작 실패. stdout={stdout[-1000:]}, stderr={stderr[-1000:]}"
        if _is_api_alive():
            return process, f"StudyHub API 서버를 {settings.studyhub_api_base_url} 에서 시작했습니다."
        time.sleep(2)

    process.terminate()
    return None, "제한 시간 안에 StudyHub API 서버가 health 응답을 반환하지 않았습니다."


def _stop_process(process: subprocess.Popen[str] | None) -> None:
    if process is None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()


def _signup_cases() -> tuple[ApiSmokeCase, list[ApiSmokeCase]]:
    unique = int(time.time())
    email = f"qa-smoke-{unique}@studyhub.local"
    happy = ApiSmokeCase(
        name="회원가입 해피케이스",
        path="/api/members/signup",
        request_json={
            "name": "QA사용자",
            "email": email,
            "password": "password123!",
            "phone": "010-1234-5678",
            "interests": ["Kotlin", "Spring Boot"],
        },
        expected_status=201,
    )
    edges = [
        ApiSmokeCase(
            name="중복 이메일 가입 차단",
            path="/api/members/signup",
            request_json=happy.request_json,
            expected_status=409,
        ),
        ApiSmokeCase(
            name="잘못된 이메일 형식 차단",
            path="/api/members/signup",
            request_json={
                "name": "QA사용자",
                "email": "not-email",
                "password": "password123!",
                "phone": None,
                "interests": [],
            },
            expected_status=400,
        ),
        ApiSmokeCase(
            name="짧은 비밀번호 차단",
            path="/api/members/signup",
            request_json={
                "name": "QA사용자",
                "email": f"qa-short-password-{unique}@studyhub.local",
                "password": "123",
                "phone": None,
                "interests": [],
            },
            expected_status=400,
        ),
    ]
    return happy, edges


def _run_api_case(case: ApiSmokeCase, timeout_seconds: int) -> ApiSmokeResult:
    exit_code, response_body, stderr, status_code = _curl_json(
        "POST",
        _api_url(case.path),
        case.request_json,
        min(timeout_seconds, 30),
    )
    response_json = response_body or stderr or "(응답 없음)"
    return ApiSmokeResult(
        name=case.name,
        path=case.path,
        request_json=case.request_json,
        response_json=response_json,
        status_code=status_code,
        curl_exit_code=exit_code,
        passed=exit_code == 0 and status_code == case.expected_status,
    )


def _format_json(value: dict[str, Any] | str) -> str:
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return value
        return json.dumps(parsed, ensure_ascii=False, indent=2)
    return json.dumps(value, ensure_ascii=False, indent=2)


def _format_api_result(result: ApiSmokeResult) -> list[str]:
    return [
        f"* 테스트 명: {result.name}",
        f"* 의도한 대로 성공했는지: {'Y' if result.passed else 'N'}",
        f"* api path: {result.path}",
        "* request json:",
        "```json",
        _format_json(result.request_json),
        "```",
        "* response json:",
        "```json",
        _format_json(result.response_json),
        "```",
        f"* http status: {result.status_code if result.status_code is not None else '확인 불가'}",
        "",
    ]


def _is_security_jwt_redis_config(title: str, body: str) -> bool:
    haystack = f"{title}\n{body}".lower()
    has_security = "security" in haystack or "spring security" in haystack or "보안" in haystack
    has_token = "jwt" in haystack or "token" in haystack or "토큰" in haystack
    has_redis = "redis" in haystack
    return has_security and has_token and has_redis


def _run_config_security_test(repo_path: Path, timeout_seconds: int) -> tuple[ConfigQaCheckResult, list[str]]:
    server_root = repo_path / "apps/server"
    command = ["./gradlew", ":modules:bootstrap:studyhub:test", "--tests", "*SecurityConfigurationTest"]
    if not server_root.exists():
        result = ConfigQaCheckResult(
            name="Security 설정 테스트",
            passed=False,
            target="apps/server",
            expected="Gradle 서버 프로젝트 존재",
            actual="apps/server 디렉토리 없음",
        )
        return result, []

    exit_code, stdout, stderr = _run_command(command, server_root, timeout_seconds)
    result = ConfigQaCheckResult(
        name="Security 설정 테스트",
        passed=exit_code == 0,
        target=" ".join(command),
        expected="exit_code=0",
        actual=f"exit_code={exit_code}",
        detail=(stdout[-1500:] or stderr[-1500:]).strip(),
    )
    command_section = [
        "## Command: ./gradlew :modules:bootstrap:studyhub:test --tests '*SecurityConfigurationTest'",
        "",
        f"- exit_code: {exit_code}",
        "",
        "### stdout",
        "```text",
        stdout.strip() or "(비어 있음)",
        "```",
        "",
        "### stderr",
        "```text",
        stderr.strip() or "(비어 있음)",
        "```",
    ]
    return result, command_section


def _verify_config_backend_health(timeout_seconds: int) -> ConfigQaCheckResult:
    exit_code, response_body, stderr, status_code = _curl_json("GET", _health_url(), None, min(timeout_seconds, 10))
    passed = exit_code == 0 and status_code == 200 and '"UP"' in response_body
    return ConfigQaCheckResult(
        name="백엔드 Health",
        passed=passed,
        target=f"GET {_health_url()}",
        expected='http_status=200, response.status="UP"',
        actual=f"http_status={status_code}, response={response_body or stderr or '(응답 없음)'}",
    )


def _verify_config_swagger(timeout_seconds: int) -> ConfigQaCheckResult:
    exit_code, response_body, stderr, status_code = _curl_json(
        "GET",
        settings.studyhub_swagger_url,
        None,
        min(timeout_seconds, 10),
    )
    return ConfigQaCheckResult(
        name="Swagger 접근",
        passed=exit_code == 0 and status_code is not None and 200 <= status_code < 400,
        target=f"GET {settings.studyhub_swagger_url}",
        expected="http_status=2xx 또는 3xx",
        actual=f"http_status={status_code}, response={response_body[:300] or stderr or '(응답 없음)'}",
    )


def _verify_config_signup_endpoint(timeout_seconds: int) -> ConfigQaCheckResult:
    happy_case, _ = _signup_cases()
    result = _run_api_case(happy_case, timeout_seconds)
    return ConfigQaCheckResult(
        name="회원가입 API 인증 예외",
        passed=result.curl_exit_code == 0 and result.status_code not in {401, 403},
        target=f"POST {_api_url(happy_case.path)}",
        expected="401/403이 아닌 응답",
        actual=f"http_status={result.status_code}, response={result.response_json}",
    )


def _verify_config_protected_api(timeout_seconds: int) -> ConfigQaCheckResult:
    path = "/api/protected-resource"
    exit_code, response_body, stderr, status_code = _curl_json("GET", _api_url(path), None, min(timeout_seconds, 10))
    return ConfigQaCheckResult(
        name="보호 API 미인증 차단",
        passed=exit_code == 0 and status_code == 401,
        target=f"GET {_api_url(path)}",
        expected="http_status=401",
        actual=f"http_status={status_code}, response={response_body or stderr or '(응답 없음)'}",
    )


def _verify_config_redis_container(repo_path: Path, timeout_seconds: int) -> ConfigQaCheckResult:
    server_root = repo_path / "apps/server"
    compose_file = server_root / "docker-compose.infra.local.yml"
    if not compose_file.exists():
        return ConfigQaCheckResult(
            name="Redis 컨테이너",
            passed=False,
            target=str(compose_file),
            expected="docker-compose.infra.local.yml 존재",
            actual="파일 없음",
        )

    exit_code, stdout, stderr = _run_command(
        ["docker", "compose", "-f", "docker-compose.infra.local.yml", "ps", "redis", "--status", "running"],
        server_root,
        min(timeout_seconds, 15),
    )
    output = stdout.strip() or stderr.strip()
    return ConfigQaCheckResult(
        name="Redis 컨테이너",
        passed=exit_code == 0 and "redis" in output.lower(),
        target="docker compose -f docker-compose.infra.local.yml ps redis --status running",
        expected="redis container running",
        actual=output or f"exit_code={exit_code}",
    )


def _format_config_qa_results(results: list[ConfigQaCheckResult]) -> list[str]:
    lines = ["## Config Runtime QA 결과", ""]
    for result in results:
        lines.extend(
            [
                f"### {result.name}",
                f"- 의도한 대로 성공했는지: {'Y' if result.passed else 'N'}",
                f"- 대상: `{result.target}`",
                f"- 기대값: {result.expected}",
                f"- 실제값: {result.actual}",
            ]
        )
        if result.detail:
            lines.extend(
                [
                    "- 상세:",
                    "```text",
                    result.detail,
                    "```",
                ]
            )
        lines.append("")
    return lines


class QAAgent:
    name = "qa"

    # 이슈 타입에 맞는 System QA 검증을 실행하고 QA 산출물을 생성한다.
    def run(self, input_data: AgentInput) -> AgentResult:
        task_dir = input_data.artifacts_root / input_data.task_id / "qa"
        task_dir.mkdir(parents=True, exist_ok=True)

        issue_type = _extract_issue_type(input_data.body)
        issue_number = _extract_metadata_value(input_data.body, "issue_number") or "unknown"
        branch_name = _branch_name(issue_type, issue_number)
        repo_path = settings.target_repo_path.expanduser().resolve()

        checks: list[tuple[str, bool, str]] = []
        command_sections: list[str] = []
        api_result_sections: list[str] = []

        repo_exists = repo_path.exists()
        checks.append(("target repository exists", repo_exists, str(repo_path)))

        current_branch = "알 수 없음"
        if repo_exists:
            repo = Repo(repo_path)
            if branch_name in {head.name for head in repo.heads}:
                repo.git.checkout(branch_name)
            current_branch = repo.active_branch.name
            checks.append(
                (
                    "expected branch is checked out",
                    current_branch == branch_name,
                    f"expected={branch_name}, actual={current_branch}",
                )
            )

        plan_dir = input_data.artifacts_root / input_data.task_id / "plans"
        dev_dir = input_data.artifacts_root / input_data.task_id / "dev"
        required_artifacts = [
            plan_dir / "architecture.md",
            plan_dir / "edge-case-checklist.md",
            dev_dir / "commit-plan.md",
            dev_dir / "dev-status.md",
            dev_dir / "implementation.patch",
            dev_dir / "test-report.md",
        ]
        for artifact in required_artifacts:
            checks.append((f"artifact exists: {artifact.name}", artifact.exists(), str(artifact)))

        if issue_type == "feFeature":
            signup_files = [
                repo_path / "apps/web/app/signup/page.tsx",
                repo_path / "apps/web/components/signup/signup-form.tsx",
                repo_path / "apps/web/lib/signup-validation.ts",
                repo_path / "apps/web/scripts/verify-signup-page.mjs",
            ]
            for path in signup_files:
                checks.append((f"signup file exists: {path.name}", path.exists(), str(path)))

            package_json = repo_path / "apps/web/package.json"
            has_signup_test = _package_has_script(package_json, "test:signup")
            checks.append(("test:signup script exists", has_signup_test, str(package_json)))
            if has_signup_test:
                exit_code, stdout, stderr = _run_command(
                    ["pnpm", "--dir", "apps/web", "test:signup"],
                    repo_path,
                    input_data.timeout_seconds,
                )
                checks.append(("test:signup passes", exit_code == 0, f"exit_code={exit_code}"))
                command_sections.extend(
                    [
                        "## Command: pnpm --dir apps/web test:signup",
                        "",
                        f"- exit_code: {exit_code}",
                        "",
                        "### stdout",
                        "```text",
                        stdout.strip() or "(비어 있음)",
                        "```",
                        "",
                        "### stderr",
                        "```text",
                        stderr.strip() or "(비어 있음)",
                        "```",
                    ]
                )

        if issue_type in {"beFeature", "apiConnect", "fullstackFeature"}:
            process: subprocess.Popen[str] | None = None
            try:
                process, server_status = _start_studyhub_api_if_needed(
                    repo_path,
                    input_data.timeout_seconds,
                )
                checks.append(("StudyHub API server is reachable", _is_api_alive(), server_status))
                if _is_api_alive():
                    happy_case, edge_cases = _signup_cases()
                    happy_result = _run_api_case(happy_case, input_data.timeout_seconds)
                    edge_results = [_run_api_case(case, input_data.timeout_seconds) for case in edge_cases]
                    checks.append(("backend happy smoke test passes", happy_result.passed, happy_result.name))
                    for result in edge_results:
                        checks.append((f"backend edge smoke test passes: {result.name}", result.passed, result.name))

                    api_result_sections.extend(
                        [
                            "## API Smoke Test 결과",
                            "",
                            "### 해피 케이스",
                            *_format_api_result(happy_result),
                            "### 최소 엣지 케이스",
                        ]
                    )
                    for result in edge_results:
                        api_result_sections.extend(_format_api_result(result))
                else:
                    api_result_sections.extend(
                        [
                            "## API Smoke Test 결과",
                            "",
                            "- StudyHub API 서버가 응답하지 않아 curl smoke test를 실행하지 못했습니다.",
                            f"- server_status: {server_status}",
                        ]
                    )
            finally:
                _stop_process(process)

        if issue_type == "config":
            config_results: list[ConfigQaCheckResult] = []
            security_config = _is_security_jwt_redis_config(input_data.title, input_data.body)
            if security_config:
                security_test, command_section = _run_config_security_test(repo_path, input_data.timeout_seconds)
                config_results.append(security_test)
                command_sections.extend(command_section)

                process: subprocess.Popen[str] | None = None
                try:
                    process, server_status = _start_studyhub_api_if_needed(
                        repo_path,
                        input_data.timeout_seconds,
                    )
                    checks.append(("StudyHub API server is reachable", _is_api_alive(), server_status))
                    if _is_api_alive():
                        config_results.extend(
                            [
                                _verify_config_backend_health(input_data.timeout_seconds),
                                _verify_config_swagger(input_data.timeout_seconds),
                                _verify_config_signup_endpoint(input_data.timeout_seconds),
                                _verify_config_protected_api(input_data.timeout_seconds),
                                _verify_config_redis_container(repo_path, input_data.timeout_seconds),
                            ]
                        )
                    else:
                        config_results.append(
                            ConfigQaCheckResult(
                                name="백엔드 런타임",
                                passed=False,
                                target=settings.studyhub_api_base_url,
                                expected="StudyHub API 서버 응답",
                                actual=server_status,
                            )
                        )
                finally:
                    _stop_process(process)
            else:
                config_results.append(
                    ConfigQaCheckResult(
                        name="Config QA 지원 범위",
                        passed=False,
                        target=issue_type,
                        expected="지원되는 config 패턴(Security/JWT/Redis 등)",
                        actual="현재 config QA Runner가 이 설정 패턴을 식별하지 못했습니다.",
                    )
                )

            for result in config_results:
                check_name = {
                    "Security 설정 테스트": "config security test passes",
                    "백엔드 Health": "config backend health is UP",
                    "Swagger 접근": "config swagger is reachable",
                    "회원가입 API 인증 예외": "config signup endpoint is permitted",
                    "보호 API 미인증 차단": "config protected api returns 401",
                    "Redis 컨테이너": "config redis container is running",
                }.get(result.name, f"config runtime check: {result.name}")
                checks.append((check_name, result.passed, result.actual))

            api_result_sections.extend(_format_config_qa_results(config_results))

        passed = all(passed for _, passed, _ in checks)
        checklist_lines = [
            f"- [{'x' if passed else ' '}] {_translate_check_name(name)} ({detail})"
            for name, passed, detail in checks
        ]
        if issue_type == "config":
            checklist_source = CONFIG_HUMAN_QA_CHECKLIST
        elif issue_type in {"beFeature", "apiConnect", "fullstackFeature"}:
            checklist_source = BE_HUMAN_QA_CHECKLIST
        else:
            checklist_source = FE_HUMAN_QA_CHECKLIST
        human_qa_lines = [f"- [ ] {item}" for item in checklist_source]
        qa_request = _extract_section(input_data.body, "Human QA Request")

        report = task_dir / "qa-report.md"
        report.write_text(
            "\n".join(
                [
                    "# System QA Report",
                    "",
                    f"- issue_type: `{issue_type}`",
                    f"- issue_number: `{issue_number}`",
                    f"- branch: `{branch_name}`",
                    f"- current_branch: `{current_branch}`",
                    f"- result: {'pass' if passed else 'fail'}",
                    f"- swagger_url: `{settings.studyhub_swagger_url}`",
                    f"- 확인 URL: `{settings.studyhub_api_base_url}`",
                    "",
                    "## QA 요청사항",
                    *(qa_request or ["추가 QA 요청사항이 없습니다."]),
                    "",
                    "## 검증 체크리스트",
                    *checklist_lines,
                    "",
                    *(command_sections or ["## Commands", "", "- 이 이슈 타입에는 실행된 명령이 없습니다."]),
                    "",
                    *api_result_sections,
                    "",
                    "## Human QA 체크리스트",
                    *human_qa_lines,
                ]
            ),
            encoding="utf-8",
        )

        checklist = task_dir / "qa-checklist.md"
        checklist.write_text(
            "\n".join(
                [
                    "# QA 체크리스트",
                    "",
                    *checklist_lines,
                    "",
                    "## Human QA 체크리스트",
                    *human_qa_lines,
                ]
            ),
            encoding="utf-8",
        )

        return AgentResult(
            status=AgentStatus.SUCCESS if passed else AgentStatus.FAILED,
            summary=f"{branch_name} QA {'통과' if passed else '실패'}.",
            artifacts=[
                ArtifactSpec("qa-report", Path(report)),
                ArtifactSpec("qa-checklist", Path(checklist)),
            ],
            error=None if passed else "QA 검증이 실패했습니다. qa-report.md를 확인하세요.",
        )
