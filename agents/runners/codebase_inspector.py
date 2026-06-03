import json
import re
from dataclasses import dataclass
from pathlib import Path

from agents.runners.base import DevRunnerContext


@dataclass(frozen=True)
class CodebaseSnapshot:
    repo_path: Path
    has_nextjs_app: bool
    has_kotlin_server: bool
    next_routes: list[str]
    api_controllers: list[str]
    migrations: list[str]
    package_scripts: dict[str, str]


# 현재 저장소에서 Dev Runner가 판단에 사용할 주요 구조를 수집한다.
def inspect_codebase(context: DevRunnerContext) -> CodebaseSnapshot:
    web_root = context.repo_path / "apps/web"
    server_root = context.repo_path / "apps/server"
    bootstrap_root = _bootstrap_root(server_root)
    return CodebaseSnapshot(
        repo_path=context.repo_path,
        has_nextjs_app=(web_root / "package.json").exists(),
        has_kotlin_server=(server_root / "build.gradle.kts").exists(),
        next_routes=_list_next_routes(web_root),
        api_controllers=_list_relative_files(
            bootstrap_root / "src/main/kotlin",
            "*Controller.kt",
        ),
        migrations=_list_relative_files(
            bootstrap_root / "src/main/resources/db/migration",
            "*.sql",
        ),
        package_scripts=_read_package_scripts(web_root / "package.json"),
    )


# 코드베이스 스냅샷을 runner artifact에 들어갈 Markdown 라인으로 변환한다.
def render_codebase_snapshot(snapshot: CodebaseSnapshot) -> list[str]:
    return [
        "## Codebase Snapshot",
        "",
        f"- repo_path: `{snapshot.repo_path}`",
        f"- has_nextjs_app: `{snapshot.has_nextjs_app}`",
        f"- has_kotlin_server: `{snapshot.has_kotlin_server}`",
        f"- next_routes: `{', '.join(snapshot.next_routes) if snapshot.next_routes else 'none'}`",
        f"- api_controllers: `{', '.join(snapshot.api_controllers) if snapshot.api_controllers else 'none'}`",
        f"- migrations: `{', '.join(snapshot.migrations) if snapshot.migrations else 'none'}`",
        f"- package_scripts: `{', '.join(sorted(snapshot.package_scripts)) if snapshot.package_scripts else 'none'}`",
        "",
    ]


# 이슈 본문에서 프론트엔드 화면 route 후보를 추출한다.
def extract_frontend_route(markdown: str) -> str | None:
    route_candidates = re.findall(r"(?<!http:)(?<!https:)`?(/[a-zA-Z0-9][a-zA-Z0-9/_-]*)`?", markdown)
    for route in route_candidates:
        if route.startswith("/api/") or route.startswith("/actuator/"):
            continue
        return route.rstrip("/") or "/"
    return None


# 이슈 본문에서 HTTP method와 API path를 추출한다.
def extract_api_endpoint(markdown: str) -> tuple[str, str] | None:
    match = re.search(
        r"\b(GET|POST|PUT|PATCH|DELETE)\s+`?(/api/[a-zA-Z0-9/_{}-]+)`?",
        markdown,
        re.IGNORECASE,
    )
    if not match:
        return None
    return match.group(1).upper(), match.group(2)


# Next.js app router 기준 route 경로를 page.tsx 파일 경로로 변환한다.
def next_page_path(repo_path: Path, route: str) -> Path:
    normalized = route.strip("/")
    if not normalized:
        return repo_path / "apps/web/app/page.tsx"
    return repo_path / "apps/web/app" / normalized / "page.tsx"


# 테스트 실행에 사용할 프론트엔드 스크립트 후보를 우선순위대로 고른다.
def frontend_test_commands(snapshot: CodebaseSnapshot) -> list[list[str]]:
    preferred = ["test", "test:signup-api-connect", "test:signup", "build"]
    return [["pnpm", "--dir", "apps/web", script] for script in preferred if script in snapshot.package_scripts]


# 테스트 실행에 사용할 백엔드 명령 후보를 고른다.
def backend_test_commands(snapshot: CodebaseSnapshot) -> list[list[str]]:
    if not snapshot.has_kotlin_server:
        return []
    return [["./gradlew", "test"]]


# 서버의 bootstrap 모듈 root를 찾는다.
def _bootstrap_root(server_root: Path) -> Path:
    root = server_root / "modules/bootstrap"
    if not root.exists():
        return root / "app"
    candidates = sorted(path for path in root.iterdir() if path.is_dir())
    return candidates[0] if candidates else root / "app"


# glob 결과를 기준 디렉토리 상대 경로 목록으로 반환한다.
def _list_relative_files(root: Path, pattern: str) -> list[str]:
    if not root.exists():
        return []
    return sorted(str(path.relative_to(root)) for path in root.rglob(pattern))


# Next.js app router page 파일을 route 목록으로 변환한다.
def _list_next_routes(web_root: Path) -> list[str]:
    app_root = web_root / "app"
    if not app_root.exists():
        return []
    routes: list[str] = []
    for page in app_root.rglob("page.tsx"):
        relative = page.parent.relative_to(app_root)
        route = "/" if str(relative) == "." else f"/{relative}"
        routes.append(route)
    return sorted(routes)


# package.json의 scripts를 안전하게 읽는다.
def _read_package_scripts(package_json: Path) -> dict[str, str]:
    if not package_json.exists():
        return {}
    try:
        data = json.loads(package_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    scripts = data.get("scripts", {})
    if not isinstance(scripts, dict):
        return {}
    return {str(key): str(value) for key, value in scripts.items()}
