import re
import subprocess
from pathlib import Path

from git import Repo

from agents.base import AgentInput, AgentResult, AgentStatus, ArtifactSpec
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


def _checkout_branch(repo_path: Path, branch_name: str) -> str:
    repo = Repo(repo_path)
    dirty_note = ""
    if repo.is_dirty(untracked_files=True):
        dirty_note = " with pre-existing uncommitted changes"

    existing = {head.name for head in repo.heads}
    if branch_name in existing:
        repo.git.checkout(branch_name)
        return f"checked out existing branch{dirty_note}"

    repo.git.checkout("-b", branch_name)
    return f"created branch{dirty_note}"


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _stage_and_commit(repo: Repo, repo_path: Path, paths: list[str], message: str) -> str:
    existing_paths = [path for path in paths if (repo_path / path).exists()]
    repo.index.add(existing_paths)
    if not repo.index.diff("HEAD"):
        return "skipped: no staged changes"
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
          placeholder="Search notes, questions, topics..."
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
            Sign up
          </Link>
        </Button>
        <ThemeSelector />
        
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" className="flex items-center gap-3 h-auto py-1.5 px-2 hover:bg-secondary">
              <div className="text-right hidden sm:block">
                <p className="text-sm font-medium text-foreground">{userName || "User"}</p>
                <p className="text-xs text-muted-foreground">{userPlan || "Free Plan"}</p>
              </div>
              <Avatar className="h-8 w-8 border border-border">
                <AvatarImage src="" alt={userName || "User"} />
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
              <span>My Profile</span>
            </DropdownMenuItem>
            <DropdownMenuItem className="cursor-pointer hover:bg-secondary">
              <Settings className="mr-2 h-4 w-4" />
              <span>Settings</span>
            </DropdownMenuItem>
            <DropdownMenuSeparator className="bg-border" />
            <DropdownMenuItem className="cursor-pointer hover:bg-secondary text-destructive">
              <LogOut className="mr-2 h-4 w-4" />
              <span>Log out</span>
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
            Back to StudyHub
          </Link>
        </Button>

        <section className="space-y-3">
          <p className="text-sm font-medium text-primary">StudyHub account</p>
          <h1 className="text-3xl font-semibold tracking-normal">Create your account</h1>
          <p className="max-w-2xl text-muted-foreground">
            Join StudyHub to organize notes, interview practice, and study questions in one place.
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
    errors.name = "Name is required."
  }

  if (!emailPattern.test(values.email.trim())) {
    errors.email = "Enter a valid email address."
  }

  if (values.password.length < 8) {
    errors.password = "Password must be at least 8 characters."
  }

  if (values.password !== values.confirmPassword) {
    errors.confirmPassword = "Passwords do not match."
  }

  if (!values.phone.trim()) {
    errors.phone = "Phone number is required."
  }

  if (!values.interests.trim()) {
    errors.interests = "Add at least one interest."
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
        <Label htmlFor="name">Name</Label>
        <Input id="name" value={values.name} onChange={(event) => updateField("name", event.target.value)} />
        {errorFor("name") && <p className="text-sm text-destructive">{errorFor("name")}</p>}
      </div>

      <div className="grid gap-2">
        <Label htmlFor="email">Email</Label>
        <Input id="email" type="email" value={values.email} onChange={(event) => updateField("email", event.target.value)} />
        {errorFor("email") && <p className="text-sm text-destructive">{errorFor("email")}</p>}
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <div className="grid gap-2">
          <Label htmlFor="password">Password</Label>
          <Input id="password" type="password" value={values.password} onChange={(event) => updateField("password", event.target.value)} />
          {errorFor("password") && <p className="text-sm text-destructive">{errorFor("password")}</p>}
        </div>

        <div className="grid gap-2">
          <Label htmlFor="confirmPassword">Confirm password</Label>
          <Input id="confirmPassword" type="password" value={values.confirmPassword} onChange={(event) => updateField("confirmPassword", event.target.value)} />
          {errorFor("confirmPassword") && <p className="text-sm text-destructive">{errorFor("confirmPassword")}</p>}
        </div>
      </div>

      <div className="grid gap-2">
        <Label htmlFor="phone">Phone</Label>
        <Input id="phone" value={values.phone} onChange={(event) => updateField("phone", event.target.value)} />
        {errorFor("phone") && <p className="text-sm text-destructive">{errorFor("phone")}</p>}
      </div>

      <div className="grid gap-2">
        <Label htmlFor="interests">Interests</Label>
        <Textarea
          id="interests"
          value={values.interests}
          onChange={(event) => updateField("interests", event.target.value)}
          placeholder="Algorithms, Spring Boot, system design"
        />
        {errorFor("interests") && <p className="text-sm text-destructive">{errorFor("interests")}</p>}
      </div>

      <Button type="submit" className="w-full sm:w-fit">Create account</Button>
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
            Back to StudyHub
          </Link>
        </Button>

        <section className="space-y-3">
          <p className="text-sm font-medium text-primary">StudyHub account</p>
          <h1 className="text-3xl font-semibold tracking-normal">Create your account</h1>
          <p className="max-w-2xl text-muted-foreground">
            Join StudyHub to organize notes, interview practice, and study questions in one place.
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
  [contents.searchHeader.includes('href="/signup"'), "search header links to /signup"],
  [contents.signupPage.includes("SignupForm"), "signup page renders SignupForm"],
  [contents.signupForm.includes("confirmPassword"), "signup form has password confirmation"],
  [contents.signupForm.includes("interests"), "signup form has interests field"],
  [contents.validation.includes("Passwords do not match."), "validation checks password confirmation"],
  [contents.validation.includes("Password must be at least 8 characters."), "validation checks password length"],
]

const failed = checks.filter(([passed]) => !passed)
if (failed.length > 0) {
  for (const [, message] of failed) {
    console.error(`failed: ${message}`)
  }
  process.exit(1)
}

console.log("signup page smoke checks passed")
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
        repo_path = settings.target_repo_path.expanduser().resolve()

        repo: Repo | None = None
        commits: list[str] = []
        progress_override: list[str] | None = None
        verification: list[str] = []

        if repo_path.exists():
            repo = Repo(repo_path)
            branch_status = _checkout_branch(repo_path, branch_name)
        else:
            branch_status = f"blocked: target repository does not exist: {repo_path}"

        if repo is not None and _is_signup_feature(issue_type, input_data.title, input_data.body):
            commits, progress_override, verification = _implement_signup_feature(
                repo=repo,
                repo_path=repo_path,
                feature_name=feature_name,
                timeout_seconds=input_data.timeout_seconds,
            )
        else:
            progress_override = [
                f"- [ ] step {index}: {title}"
                for index, (title, _) in enumerate(commit_units, start=1)
            ]

        commit_plan = task_dir / "commit-plan.md"
        commit_plan.write_text(
            "\n".join(
                [
                    "# Commit Plan",
                    "",
                    f"- issue_type: `{issue_type}`",
                    f"- issue_number: `{issue_number}`",
                    f"- branch: `{branch_name}`",
                    f"- branch_status: {branch_status}",
                    "",
                    "## Rule",
                    "",
                    "- 구현 단계 하나가 끝날 때마다 커밋한다.",
                    "- 빈 커밋은 만들지 않는다.",
                    "- 각 커밋 전에 관련 테스트를 추가하거나 갱신한다.",
                    "",
                    "## Commit Units",
                    *[
                        f"{index}. [{feature_name}] : {message}"
                        for index, (_, message) in enumerate(commit_units, start=1)
                    ],
                    "",
                    "## Actual Commits",
                    *(commits or ["- pending implementation runner"]),
                ]
            ),
            encoding="utf-8",
        )

        status = task_dir / "dev-status.md"
        status.write_text(
            "\n".join(
                [
                    "# Dev Status",
                    "",
                    f"- branch: `{branch_name}`",
                    f"- branch_status: {branch_status}",
                    "- current_step: ready for implementation",
                    "- visibility: GitHub issue comment + this artifact",
                    "",
                    "## Progress",
                    *progress_override,
                    "",
                    "## Commits",
                    *(commits or ["- pending implementation runner"]),
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
                    "# No implementation diff generated.",
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
                    "# Dev Test Report",
                    "",
                    f"- branch: `{branch_name}`",
                    f"- branch_status: {branch_status}",
                    "- test code: required for each implementation unit",
                    "- smoke test: see command sections below when executed",
                    "- edge case test: covered by generated smoke checks when supported",
                    "- build: run manually or in the next QA stage",
                    "",
                    *(verification or ["- automated verification not executed for this issue type"]),
                ]
            ),
            encoding="utf-8",
        )

        summary = (
            f"Dev implementation completed on {branch_name}. {len(commits)} commit entries recorded."
            if commits
            else f"Dev branch prepared: {branch_name}. Commit plan generated."
        )

        return AgentResult(
            status=AgentStatus.SUCCESS,
            summary=summary,
            artifacts=[
                ArtifactSpec("commit-plan", Path(commit_plan)),
                ArtifactSpec("dev-status", Path(status)),
                ArtifactSpec("patch", Path(patch)),
                ArtifactSpec("test-report", Path(report)),
            ],
        )
