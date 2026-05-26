import re
import subprocess
from pathlib import Path

from git import Repo

from agents.base import AgentInput, AgentResult, AgentStatus, ArtifactSpec
from agents.runners.base import DevRunner, DevRunnerContext, DevRunnerResult
from agents.runners.docs_runner import DocsRunner
from agents.runners.infra_runner import InfraRunner
from agents.runners.kotlin_spring_runner import KotlinSpringRunner
from agents.runners.nextjs_runner import NextJsRunner
from orchestrator.core.settings import settings


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
    return "unspecified"


def _extract_refactor_request(markdown: str) -> list[str]:
    return _extract_section(markdown, "Human Refactor Request")


def _is_refactor_mode(markdown: str) -> bool:
    return bool(_extract_refactor_request(markdown))


def _branch_prefix(issue_type: str) -> str:
    return {
        "beFeature": "feature(BE)",
        "feFeature": "feature(FE)",
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


def _feature_name(title: str) -> str:
    cleaned = re.sub(r"\[[^\]]+\]", "", title).strip()
    return cleaned or title.strip() or "작업"


def _commit_units(issue_type: str) -> list[tuple[str, str]]:
    if issue_type == "feFeature":
        return [
            ("UI 진입점 추가", "버튼/라우팅 추가"),
            ("화면 구현", "페이지 또는 컴포넌트 구현"),
            ("테스트 추가", "프론트엔드 테스트 코드 추가"),
            ("검증 정리", "빌드와 린트 검증"),
        ]
    if issue_type == "beFeature":
        return [
            ("도메인/UseCase 구현", "도메인과 application 흐름 추가"),
            ("API/인프라 연결", "controller, DTO, persistence 연결"),
            ("테스트 추가", "단위/통합 테스트 코드 추가"),
            ("검증 정리", "서버 빌드와 테스트 검증"),
        ]
    if issue_type == "apiConnect":
        return [
            ("API contract 정리", "request/response schema 확정"),
            ("연동 구현", "FE 호출과 BE endpoint 연결"),
            ("테스트 추가", "contract와 실패 케이스 테스트 추가"),
            ("검증 정리", "FE/BE smoke test 검증"),
        ]
    if issue_type in {"bugfix", "hotfix"}:
        return [
            ("재현 테스트 추가", "버그 재현 또는 회귀 테스트 추가"),
            ("수정 구현", "최소 범위 수정"),
            ("검증 정리", "회귀 테스트와 빌드 검증"),
        ]
    return [
        ("변경 범위 구현", "요구사항 기반 최소 변경"),
        ("테스트 추가", "관련 테스트 코드 추가"),
        ("검증 정리", "빌드와 smoke test 검증"),
    ]


def _requires_backend_style(issue_type: str) -> bool:
    return issue_type in {"beFeature", "apiConnect", "bugfix", "hotfix"}


def _backend_style_skill_path() -> Path:
    return Path.home() / ".codex/skills/usecase-orchestration-style/SKILL.md"


def _backend_style_lines(issue_type: str) -> list[str]:
    if not _requires_backend_style(issue_type):
        return ["- backend orchestration style skill: 이 이슈 타입에는 필수가 아닙니다."]

    skill_path = _backend_style_skill_path()
    backend_rules_path = Path("rules/backend-runner.md")
    return [
        "- backend orchestration style skill: required",
        f"- skill_path: `{skill_path}`",
        f"- backend_runner_rules: `{backend_rules_path}`",
        "- localization_rules: `rules/localization.md`",
        "- 컨트롤러는 얇게 유지하고 request/response DTO는 컨트롤러 파일 밖의 별도 파일로 둔다.",
        "- domain/application/port/infrastructure/bootstrap 경계를 지킨다.",
        "- 메인 서비스 메서드는 유스케이스 흐름이 보이게 작성한다.",
        "- 의미 없는 private 메서드와 한 줄 위임 메서드를 남발하지 않는다.",
        "- 정책, 검증, 외부 연동, 상태 변경 책임은 이름이 명확한 외부 책임 객체로 분리한다.",
        "- 책임 객체의 public 메서드에는 한국어 한 줄 주석을 작성한다.",
        "- 클래스와 메서드는 유비쿼터스 언어와 주어/동사/목적어가 드러나게 명명한다.",
        "- 사용자 응답, 프론트엔드 검증 메시지, 내부 예외, 로그는 한국어를 우선 사용한다.",
        "- 사용자 응답 메시지는 안전하고 이해 가능하게 작성하고, 내부 로그에는 who/what/requestData/reason을 남긴다.",
    ]


def _dev_runners() -> list[DevRunner]:
    return [
        NextJsRunner(),
        KotlinSpringRunner(),
        DocsRunner(),
        InfraRunner(),
    ]


def _select_runners(context: DevRunnerContext) -> list[DevRunner]:
    matched = [runner for runner in _dev_runners() if runner.can_handle(context)]
    if context.issue_type == "apiConnect":
        return matched
    return matched[:1]


def _checkout_branch(repo_path: Path, branch_name: str) -> str:
    repo = Repo(repo_path)
    dirty_note = ""
    if repo.is_dirty(untracked_files=True):
        dirty_note = " (기존 미커밋 변경사항 있음)"

    existing = {head.name for head in repo.heads}
    if branch_name in existing:
        repo.git.checkout(branch_name)
        return f"기존 브랜치 체크아웃{dirty_note}"

    repo.git.checkout("-b", branch_name)
    return f"새 브랜치 생성{dirty_note}"


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _stage_and_commit(repo: Repo, repo_path: Path, paths: list[str], message: str) -> str:
    existing_paths = [path for path in paths if (repo_path / path).exists()]
    repo.index.add(existing_paths)
    if not repo.index.diff("HEAD"):
        return "스킵: 스테이징된 변경사항 없음"
    commit = repo.index.commit(message)
    return commit.hexsha[:12]


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


def _is_signup_feature(issue_type: str, title: str, body: str) -> bool:
    haystack = f"{title}\n{body}"
    return issue_type == "feFeature" and ("회원" in haystack and "가입" in haystack)


def _update_package_script(package_json: Path) -> None:
    import json

    data = json.loads(package_json.read_text(encoding="utf-8"))
    scripts = data.setdefault("scripts", {})
    scripts["test:signup"] = "node scripts/verify-signup-page.mjs"
    package_json.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _implement_signup_feature(
    repo: Repo,
    repo_path: Path,
    feature_name: str,
    timeout_seconds: int,
) -> tuple[list[str], list[str], list[str]]:
    commits: list[str] = []
    progress: list[str] = []
    verification: list[str] = []

    _write_text(repo_path / "apps/web/app/signup/page.tsx", _signup_page_shell_content())
    _write_text(repo_path / "apps/web/components/dashboard/search-header.tsx", _search_header_content())
    commit_hash = _stage_and_commit(
        repo,
        repo_path,
        [
            "apps/web/app/signup/page.tsx",
            "apps/web/components/dashboard/search-header.tsx",
        ],
        f"[{feature_name}] : 버튼/라우팅 추가",
    )
    commits.append(f"1. {commit_hash} [{feature_name}] : 버튼/라우팅 추가")
    progress.append("- [x] step 1: UI 진입점 추가")

    _write_text(repo_path / "apps/web/lib/signup-validation.ts", _signup_validation_content())
    _write_text(repo_path / "apps/web/components/signup/signup-form.tsx", _signup_form_content())
    _write_text(repo_path / "apps/web/app/signup/page.tsx", _signup_page_full_content())
    commit_hash = _stage_and_commit(
        repo,
        repo_path,
        [
            "apps/web/lib/signup-validation.ts",
            "apps/web/components/signup/signup-form.tsx",
            "apps/web/app/signup/page.tsx",
        ],
        f"[{feature_name}] : 페이지 또는 컴포넌트 구현",
    )
    commits.append(f"2. {commit_hash} [{feature_name}] : 페이지 또는 컴포넌트 구현")
    progress.append("- [x] step 2: 화면 구현")

    _write_text(repo_path / "apps/web/scripts/verify-signup-page.mjs", _signup_test_content())
    _update_package_script(repo_path / "apps/web/package.json")
    commit_hash = _stage_and_commit(
        repo,
        repo_path,
        [
            "apps/web/scripts/verify-signup-page.mjs",
            "apps/web/package.json",
        ],
        f"[{feature_name}] : 프론트엔드 테스트 코드 추가",
    )
    commits.append(f"3. {commit_hash} [{feature_name}] : 프론트엔드 테스트 코드 추가")
    progress.append("- [x] step 3: 테스트 추가")

    exit_code, stdout, stderr = _run_command(
        ["pnpm", "--dir", "apps/web", "test:signup"],
        repo_path,
        timeout_seconds,
    )
    verification.extend(
        [
            "## test:signup",
            "",
            f"- exit_code: {exit_code}",
            "",
            "### stdout",
            "```text",
            stdout.strip() or "(empty)",
            "```",
            "",
            "### stderr",
            "```text",
            stderr.strip() or "(empty)",
            "```",
        ]
    )
    progress.append(
        "- [x] step 4: 검증 정리" if exit_code == 0 else "- [ ] step 4: 검증 정리"
    )
    commits.append("4. no commit [검증 정리] : test:signup 실행")

    return commits, progress, verification


def _search_header_content() -> str:
    return '''"use client"

import Link from "next/link"
import { Search, Command, User, Settings, LogOut, UserPlus } from "lucide-react"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar"
import { Kbd } from "@/components/ui/kbd"
import { ThemeSelector } from "@/components/theme-selector"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"

interface SearchHeaderProps {
  onNavigate?: (section: string) => void
  userName?: string
  userPlan?: string
}

export function SearchHeader({ onNavigate, userName, userPlan }: SearchHeaderProps) {
  return (
    <header className="flex h-14 items-center justify-between border-b border-border bg-background px-6">
      <div className="relative flex-1 max-w-md">
        <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          placeholder="노트, 질문, 주제를 검색하세요"
          className="h-9 bg-secondary border-0 pl-9 pr-12 text-sm placeholder:text-muted-foreground focus-visible:ring-1 focus-visible:ring-primary"
        />
        <div className="absolute right-3 top-1/2 -translate-y-1/2 flex items-center gap-0.5">
          <Kbd><Command className="h-3 w-3" /></Kbd>
          <Kbd>K</Kbd>
        </div>
      </div>

      <div className="flex items-center gap-2">
        <Button asChild size="sm" variant="outline" className="hidden sm:inline-flex">
          <Link href="/signup">
            <UserPlus className="h-4 w-4" />
            회원가입
          </Link>
        </Button>
        <ThemeSelector />
        
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" className="flex items-center gap-3 h-auto py-1.5 px-2 hover:bg-secondary">
              <div className="text-right hidden sm:block">
                <p className="text-sm font-medium text-foreground">{userName || "사용자"}</p>
                <p className="text-xs text-muted-foreground">{userPlan || "무료 플랜"}</p>
              </div>
              <Avatar className="h-8 w-8 border border-border">
                <AvatarImage src="" alt={userName || "사용자"} />
                <AvatarFallback className="bg-secondary text-secondary-foreground text-xs">
                  {userName ? userName.split(" ").map((n) => n[0]).join("").toUpperCase() : "U"}
                </AvatarFallback>
              </Avatar>
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-48 bg-popover border-border">
            <DropdownMenuItem 
              className="cursor-pointer hover:bg-secondary"
              onClick={() => onNavigate?.("profile")}
            >
              <User className="mr-2 h-4 w-4" />
              <span>내 프로필</span>
            </DropdownMenuItem>
            <DropdownMenuItem className="cursor-pointer hover:bg-secondary">
              <Settings className="mr-2 h-4 w-4" />
              <span>설정</span>
            </DropdownMenuItem>
            <DropdownMenuSeparator className="bg-border" />
            <DropdownMenuItem className="cursor-pointer hover:bg-secondary text-destructive">
              <LogOut className="mr-2 h-4 w-4" />
              <span>로그아웃</span>
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  )
}
'''


def _signup_page_shell_content() -> str:
    return '''import Link from "next/link"
import { ArrowLeft } from "lucide-react"

import { Button } from "@/components/ui/button"

export default function SignupPage() {
  return (
    <main className="min-h-screen bg-background px-6 py-10 text-foreground">
      <div className="mx-auto flex w-full max-w-3xl flex-col gap-8">
        <Button asChild variant="ghost" className="w-fit px-0">
          <Link href="/">
            <ArrowLeft className="h-4 w-4" />
            StudyHub로 돌아가기
          </Link>
        </Button>

        <section className="space-y-3">
          <p className="text-sm font-medium text-primary">StudyHub 계정</p>
          <h1 className="text-3xl font-semibold tracking-normal">계정을 만들어보세요</h1>
          <p className="max-w-2xl text-muted-foreground">
            StudyHub에서 노트, 면접 연습, 학습 질문을 한곳에 정리하세요.
          </p>
        </section>
      </div>
    </main>
  )
}
'''


def _signup_validation_content() -> str:
    return '''export interface SignupFormValues {
  name: string
  email: string
  password: string
  confirmPassword: string
  phone: string
  interests: string
}

export interface SignupValidationResult {
  isValid: boolean
  errors: Partial<Record<keyof SignupFormValues, string>>
}

const emailPattern = /^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$/

export function validateSignup(values: SignupFormValues): SignupValidationResult {
  const errors: SignupValidationResult["errors"] = {}

  if (!values.name.trim()) {
    errors.name = "이름을 입력해주세요."
  }

  if (!emailPattern.test(values.email.trim())) {
    errors.email = "올바른 이메일 주소를 입력해주세요."
  }

  if (values.password.length < 8) {
    errors.password = "비밀번호는 8자 이상이어야 합니다."
  }

  if (values.password !== values.confirmPassword) {
    errors.confirmPassword = "비밀번호가 서로 일치하지 않습니다."
  }

  if (!values.phone.trim()) {
    errors.phone = "전화번호를 입력해주세요."
  }

  if (!values.interests.trim()) {
    errors.interests = "관심 영역을 하나 이상 입력해주세요."
  }

  return {
    isValid: Object.keys(errors).length === 0,
    errors,
  }
}
'''


def _signup_form_content() -> str:
    return '''"use client"

import { FormEvent, useMemo, useState } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { validateSignup, type SignupFormValues } from "@/lib/signup-validation"

const initialValues: SignupFormValues = {
  name: "",
  email: "",
  password: "",
  confirmPassword: "",
  phone: "",
  interests: "",
}

export function SignupForm() {
  const [values, setValues] = useState<SignupFormValues>(initialValues)
  const [submitted, setSubmitted] = useState(false)

  const validation = useMemo(() => validateSignup(values), [values])

  const updateField = (field: keyof SignupFormValues, value: string) => {
    setValues((current) => ({ ...current, [field]: value }))
  }

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setSubmitted(true)

    if (!validation.isValid) {
      return
    }
  }

  const errorFor = (field: keyof SignupFormValues) => submitted ? validation.errors[field] : undefined

  return (
    <form onSubmit={handleSubmit} className="grid gap-5 rounded-lg border border-border bg-card p-6 shadow-sm">
      <div className="grid gap-2">
        <Label htmlFor="name">이름</Label>
        <Input id="name" value={values.name} onChange={(event) => updateField("name", event.target.value)} />
        {errorFor("name") && <p className="text-sm text-destructive">{errorFor("name")}</p>}
      </div>

      <div className="grid gap-2">
        <Label htmlFor="email">이메일</Label>
        <Input id="email" type="email" value={values.email} onChange={(event) => updateField("email", event.target.value)} />
        {errorFor("email") && <p className="text-sm text-destructive">{errorFor("email")}</p>}
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <div className="grid gap-2">
          <Label htmlFor="password">비밀번호</Label>
          <Input id="password" type="password" value={values.password} onChange={(event) => updateField("password", event.target.value)} />
          {errorFor("password") && <p className="text-sm text-destructive">{errorFor("password")}</p>}
        </div>

        <div className="grid gap-2">
          <Label htmlFor="confirmPassword">비밀번호 확인</Label>
          <Input id="confirmPassword" type="password" value={values.confirmPassword} onChange={(event) => updateField("confirmPassword", event.target.value)} />
          {errorFor("confirmPassword") && <p className="text-sm text-destructive">{errorFor("confirmPassword")}</p>}
        </div>
      </div>

      <div className="grid gap-2">
        <Label htmlFor="phone">전화번호</Label>
        <Input id="phone" value={values.phone} onChange={(event) => updateField("phone", event.target.value)} />
        {errorFor("phone") && <p className="text-sm text-destructive">{errorFor("phone")}</p>}
      </div>

      <div className="grid gap-2">
        <Label htmlFor="interests">관심 영역</Label>
        <Textarea
          id="interests"
          value={values.interests}
          onChange={(event) => updateField("interests", event.target.value)}
          placeholder="알고리즘, Spring Boot, 시스템 설계"
        />
        {errorFor("interests") && <p className="text-sm text-destructive">{errorFor("interests")}</p>}
      </div>

      <Button type="submit" className="w-full sm:w-fit">계정 만들기</Button>
    </form>
  )
}
'''


def _signup_page_full_content() -> str:
    return '''import Link from "next/link"
import { ArrowLeft } from "lucide-react"

import { SignupForm } from "@/components/signup/signup-form"
import { Button } from "@/components/ui/button"

export default function SignupPage() {
  return (
    <main className="min-h-screen bg-background px-6 py-10 text-foreground">
      <div className="mx-auto flex w-full max-w-3xl flex-col gap-8">
        <Button asChild variant="ghost" className="w-fit px-0">
          <Link href="/">
            <ArrowLeft className="h-4 w-4" />
            StudyHub로 돌아가기
          </Link>
        </Button>

        <section className="space-y-3">
          <p className="text-sm font-medium text-primary">StudyHub 계정</p>
          <h1 className="text-3xl font-semibold tracking-normal">계정을 만들어보세요</h1>
          <p className="max-w-2xl text-muted-foreground">
            StudyHub에서 노트, 면접 연습, 학습 질문을 한곳에 정리하세요.
          </p>
        </section>

        <SignupForm />
      </div>
    </main>
  )
}
'''


def _signup_test_content() -> str:
    return '''import { readFileSync } from "node:fs"
import { join } from "node:path"

const root = process.cwd()
const files = {
  signupPage: join(root, "app/signup/page.tsx"),
  signupForm: join(root, "components/signup/signup-form.tsx"),
  validation: join(root, "lib/signup-validation.ts"),
  searchHeader: join(root, "components/dashboard/search-header.tsx"),
}

const contents = Object.fromEntries(
  Object.entries(files).map(([key, path]) => [key, readFileSync(path, "utf8")]),
)

const checks = [
  [contents.searchHeader.includes('href="/signup"'), "회원가입 링크 확인"],
  [contents.signupPage.includes("SignupForm"), "회원가입 폼 렌더링 확인"],
  [contents.signupForm.includes("confirmPassword"), "비밀번호 확인 필드 확인"],
  [contents.signupForm.includes("interests"), "관심 영역 필드 확인"],
  [contents.validation.includes("비밀번호가 서로 일치하지 않습니다."), "비밀번호 확인 검증"],
  [contents.validation.includes("비밀번호는 8자 이상이어야 합니다."), "비밀번호 길이 검증"],
]

const failed = checks.filter(([passed]) => !passed)
if (failed.length > 0) {
  for (const [, message] of failed) {
    console.error(`실패: ${message}`)
  }
  process.exit(1)
}

console.log("회원가입 화면 smoke 검증 통과")
'''


class DevAgent:
    name = "dev"

    def run(self, input_data: AgentInput) -> AgentResult:
        task_dir = input_data.artifacts_root / input_data.task_id / "dev"
        task_dir.mkdir(parents=True, exist_ok=True)
        issue_type = _extract_issue_type(input_data.body)
        issue_number = _extract_metadata_value(input_data.body, "issue_number") or "unknown"
        branch_name = _branch_name(issue_type, issue_number)
        feature_name = _feature_name(input_data.title)
        commit_units = _commit_units(issue_type)
        backend_style_lines = _backend_style_lines(issue_type)
        refactor_request = _extract_refactor_request(input_data.body)
        is_refactor_mode = _is_refactor_mode(input_data.body)
        repo_path = settings.target_repo_path.expanduser().resolve()

        repo: Repo | None = None
        commits: list[str] = []
        progress_override: list[str] | None = None
        verification: list[str] = []
        runner_name = "none"
        runner_error: str | None = None
        runner_artifacts: list[ArtifactSpec] = []
        result_status = AgentStatus.SUCCESS

        if repo_path.exists():
            repo = Repo(repo_path)
            branch_status = _checkout_branch(repo_path, branch_name)
        else:
            branch_status = f"blocked: target repository does not exist: {repo_path}"

        if repo is not None:
            context = DevRunnerContext(
                task_id=input_data.task_id,
                title=input_data.title,
                body=input_data.body,
                issue_type=issue_type,
                issue_number=issue_number,
                branch_name=branch_name,
                feature_name=feature_name,
                repo=repo,
                repo_path=repo_path,
                task_dir=task_dir,
                timeout_seconds=input_data.timeout_seconds,
            )
            runners = _select_runners(context)
            if not runners:
                result_status = AgentStatus.NEEDS_HUMAN
                runner_error = f"issue_type={issue_type}를 처리할 수 있는 Dev Runner가 없습니다."
                verification = [
                    "## runner_selection",
                    "",
                    "- status: needs_human",
                    f"- reason: {runner_error}",
                ]
            else:
                runner_names: list[str] = []
                progress_lines: list[str] = []
                verification_lines: list[str] = []
                errors: list[str] = []
                for runner in runners:
                    runner_names.append(runner.name)
                    runner_result: DevRunnerResult = runner.run(context)
                    if runner_result.status != AgentStatus.SUCCESS:
                        result_status = runner_result.status
                    commits.extend(runner_result.commits)
                    progress_lines.extend(runner_result.progress)
                    verification_lines.extend(runner_result.verification)
                    runner_artifacts.extend(runner_result.artifacts)
                    if runner_result.error:
                        errors.append(f"{runner.name}: {runner_result.error}")

                runner_name = ", ".join(runner_names)
                progress_override = progress_lines
                verification = verification_lines
                runner_error = "; ".join(errors) if errors else None

        if progress_override is None:
            progress_override = [
                f"- [ ] step {index}: {title}"
                for index, (title, _) in enumerate(commit_units, start=1)
            ]

        if repo is None:
            result_status = AgentStatus.FAILED
            runner_error = branch_status
            verification = [
                "## Runner 선택",
                "",
                "- status: failed",
                f"- reason: {branch_status}",
            ]

        commit_plan = task_dir / "commit-plan.md"
        commit_plan.write_text(
            "\n".join(
                [
                    "# 커밋 계획",
                    "",
                    f"- issue_type: `{issue_type}`",
                    f"- issue_number: `{issue_number}`",
                    f"- branch: `{branch_name}`",
                    f"- branch_status: {branch_status}",
                    f"- selected_runner: `{runner_name}`",
                    f"- mode: `{'refactor' if is_refactor_mode else 'develop'}`",
                    "",
                    "## 규칙",
                    "",
                    "- 구현 단계 하나가 끝날 때마다 커밋한다.",
                    "- 빈 커밋은 만들지 않는다.",
                    "- 각 커밋 전에 관련 테스트를 추가하거나 갱신한다.",
                    "",
                    "## Backend Style Skill",
                    *backend_style_lines,
                    "",
                    *(
                        [
                            "## 사람 리팩터링 요청",
                            *refactor_request,
                            "",
                        ]
                        if is_refactor_mode
                        else []
                    ),
                    "## 커밋 단위",
                    *[
                        f"{index}. [{feature_name}] : {message}"
                        for index, (_, message) in enumerate(commit_units, start=1)
                    ],
                    "",
                    "## 실제 커밋",
                    *(commits or ["- 구현 Runner 실행 대기 중"]),
                    "",
                    "## Runner 결과",
                    f"- status: `{result_status.value}`",
                    f"- error: `{runner_error or 'none'}`",
                ]
            ),
            encoding="utf-8",
        )

        status = task_dir / "dev-status.md"
        status.write_text(
            "\n".join(
                [
                    "# Dev 상태",
                    "",
                    f"- branch: `{branch_name}`",
                    f"- branch_status: {branch_status}",
                    f"- selected_runner: `{runner_name}`",
                    f"- mode: `{'refactor' if is_refactor_mode else 'develop'}`",
                    f"- current_step: {'완료' if commits else '구현 전 중단'}",
                    "- visibility: GitHub 이슈 댓글과 이 artifact에서 확인합니다.",
                    "",
                    "## 백엔드 스타일",
                    *backend_style_lines,
                    "",
                    *(
                        [
                            "## 사람 리팩터링 요청",
                            *refactor_request,
                            "",
                        ]
                        if is_refactor_mode
                        else []
                    ),
                    "## 진행 상황",
                    *progress_override,
                    "",
                    "## 커밋",
                    *(commits or ["- 구현 Runner 실행 대기 중"]),
                    "",
                    "## Runner 결과",
                    f"- status: `{result_status.value}`",
                    f"- error: `{runner_error or 'none'}`",
                ]
            ),
            encoding="utf-8",
        )

        style_guide = task_dir / "backend-style-checklist.md"
        style_guide.write_text(
            "\n".join(
                [
                    "# 백엔드 스타일 체크리스트",
                    "",
                    f"- mode: `{'refactor' if is_refactor_mode else 'develop'}`",
                    "",
                    *backend_style_lines,
                    "",
                    *(
                        [
                            "## 사람 리팩터링 요청",
                            *refactor_request,
                            "",
                        ]
                        if is_refactor_mode
                        else []
                    ),
                    "## 리뷰 항목",
                    "- [ ] 메인 서비스 메서드가 조회, 검증, 수행/요청, 기록/상태 변경, 반환 흐름을 직접 보여준다.",
                    "- [ ] 정책적 의미가 있는 로직은 명확한 책임 객체로 분리되어 있다.",
                    "- [ ] 책임 객체 public 메서드에는 한국어 한 줄 주석이 있다.",
                    "- [ ] validate/process/handle/execute 같은 모호한 이름을 남발하지 않는다.",
                    "- [ ] 외부 시스템 호출 이름에 외부 경계 또는 제휴사가 드러난다.",
                    "- [ ] 상태 변경, 정합성, 재시도, 멱등성 지점이 코드와 로그에서 추적 가능하다.",
                ]
            ),
            encoding="utf-8",
        )

        patch = task_dir / "implementation.patch"
        if repo is not None:
            diff = repo.git.diff("main...HEAD")
        else:
            diff = ""
        patch.write_text(
            diff
            or "\n".join(
                [
                    "# 생성된 구현 diff가 없습니다.",
                    f"# task_id={input_data.task_id}",
                    f"# branch={branch_name}",
                ]
            ),
            encoding="utf-8",
        )

        report = task_dir / "test-report.md"
        report.write_text(
            "\n".join(
                [
                    "# Dev 테스트 리포트",
                    "",
                    f"- branch: `{branch_name}`",
                    f"- branch_status: {branch_status}",
                    f"- selected_runner: `{runner_name}`",
                    f"- runner_status: `{result_status.value}`",
                    "- test code: 각 구현 단위마다 테스트 코드가 필요합니다.",
                    "- smoke test: 실행된 경우 아래 command 섹션에서 확인하세요.",
                    "- edge case test: 지원되는 경우 생성된 smoke check에 포함됩니다.",
                    "- build: 수동 또는 다음 QA 단계에서 실행합니다.",
                    "",
                    *(verification or ["- 이 이슈 타입에는 자동 검증이 실행되지 않았습니다."]),
                ]
            ),
            encoding="utf-8",
        )

        action_label = "리팩터링" if is_refactor_mode else "개발 구현"
        summary = (
            f"{action_label}이 {runner_name}에 의해 {branch_name}에서 완료되었습니다. 커밋 기록 {len(commits)}개가 생성되었습니다."
            if commits
            else (
                f"{action_label} 러너가 {branch_name}에서 구현 전 중단되었습니다: {runner_error}"
                if runner_error
                else f"{action_label} 브랜치가 준비되었습니다: {branch_name}. 커밋 계획이 생성되었습니다."
            )
        )

        return AgentResult(
            status=result_status,
            summary=summary,
            error=runner_error,
            artifacts=[
                ArtifactSpec("commit-plan", Path(commit_plan)),
                ArtifactSpec("dev-status", Path(status)),
                ArtifactSpec("backend-style-checklist", Path(style_guide)),
                ArtifactSpec("patch", Path(patch)),
                ArtifactSpec("test-report", Path(report)),
                *runner_artifacts,
            ],
        )
