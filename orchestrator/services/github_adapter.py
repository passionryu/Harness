import json
import re
import subprocess
import tempfile
from pathlib import Path

import httpx


class GitHubAdapter:
    def __init__(self, token: str | None, use_gh_cli: bool = False):
        self.token = token
        self.use_gh_cli = use_gh_cli

    def is_configured(self) -> bool:
        return bool(self.token) or self.use_gh_cli

    # gh CLI가 사용할 owner/repo 문자열을 만든다.
    def _repo(self, owner: str, repo: str) -> str:
        return f"{owner}/{repo}"

    # gh CLI를 실행하고 JSON 출력을 반환한다.
    def _run_gh_json(self, command: list[str]) -> dict | list:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
        if completed.returncode != 0:
            raise RuntimeError((completed.stderr or completed.stdout or f"exit_code={completed.returncode}").strip())
        return json.loads(completed.stdout or "{}")

    # gh CLI를 실행하고 성공 여부만 확인한다.
    def _run_gh(self, command: list[str]) -> None:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
        if completed.returncode != 0:
            raise RuntimeError((completed.stderr or completed.stdout or f"exit_code={completed.returncode}").strip())

    # gh issue payload를 GitHub REST API payload 형태에 가깝게 변환한다.
    def _normalize_issue(self, payload: dict) -> dict:
        normalized = dict(payload)
        if "url" in normalized and "html_url" not in normalized:
            normalized["html_url"] = normalized["url"]
        labels = normalized.get("labels") or []
        normalized["labels"] = [
            {"name": item.get("name")}
            for item in labels
            if isinstance(item, dict) and item.get("name")
        ]
        return normalized

    # gh CLI 인증을 사용해 GitHub 이슈 댓글을 작성한다.
    def _create_issue_comment_with_gh(self, owner: str, repo: str, issue_number: int, body: str) -> None:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as file:
            file.write(body)
            body_path = Path(file.name)
        try:
            completed = subprocess.run(
                [
                    "gh",
                    "issue",
                    "comment",
                    str(issue_number),
                    "--repo",
                    self._repo(owner, repo),
                    "--body-file",
                    str(body_path),
                ],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            if completed.returncode != 0:
                raise RuntimeError((completed.stderr or completed.stdout or f"exit_code={completed.returncode}").strip())
        finally:
            body_path.unlink(missing_ok=True)

    # gh CLI 인증을 사용해 GitHub 이슈를 생성한다.
    def _create_issue_with_gh(
        self,
        owner: str,
        repo: str,
        title: str,
        body: str,
        labels: list[str] | None = None,
    ) -> dict:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as file:
            file.write(body)
            body_path = Path(file.name)
        command = [
            "gh",
            "issue",
            "create",
            "--repo",
            self._repo(owner, repo),
            "--title",
            title,
            "--body-file",
            str(body_path),
        ]
        for label in labels or []:
            command.extend(["--label", label])
        try:
            completed = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
            if completed.returncode != 0:
                raise RuntimeError((completed.stderr or completed.stdout or f"exit_code={completed.returncode}").strip())
            issue_url = completed.stdout.strip()
            match = re.search(r"/issues/(\d+)", issue_url)
            if not match:
                raise RuntimeError(f"생성된 이슈 번호를 확인할 수 없습니다: {issue_url}")
            return self.get_issue(owner, repo, int(match.group(1)))
        finally:
            body_path.unlink(missing_ok=True)

    def create_issue(
        self,
        owner: str,
        repo: str,
        title: str,
        body: str,
        labels: list[str] | None = None,
    ) -> dict:
        if not self.token:
            if self.use_gh_cli:
                return self._create_issue_with_gh(owner, repo, title, body, labels)
            raise ValueError("GitHub token이 설정되어 있지 않습니다.")

        url = f"https://api.github.com/repos/{owner}/{repo}/issues"
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        payload: dict[str, object] = {"title": title, "body": body}
        if labels:
            payload["labels"] = labels
        response = httpx.post(url, headers=headers, json=payload, timeout=20)
        try:
            response.raise_for_status()
            return response.json()
        except Exception:
            if self.use_gh_cli:
                return self._create_issue_with_gh(owner, repo, title, body, labels)
            raise

    def create_issue_comment(
        self,
        owner: str,
        repo: str,
        issue_number: int,
        body: str,
    ) -> None:
        if not self.token:
            if self.use_gh_cli:
                self._create_issue_comment_with_gh(owner, repo, issue_number, body)
                return
            raise ValueError("GitHub token이 설정되어 있지 않습니다.")

        url = f"https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}/comments"
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        response = httpx.post(url, headers=headers, json={"body": body}, timeout=20)
        try:
            response.raise_for_status()
        except Exception:
            if self.use_gh_cli:
                self._create_issue_comment_with_gh(owner, repo, issue_number, body)
                return
            raise

    # GitHub 이슈 댓글을 수정한다.
    def update_issue_comment(self, owner: str, repo: str, comment_id: int | str, body: str) -> None:
        if not self.token:
            if self.use_gh_cli:
                if isinstance(comment_id, str) and not comment_id.isdigit():
                    self._run_gh(
                        [
                            "gh",
                            "api",
                            "graphql",
                            "-f",
                            "query=mutation($id:ID!,$body:String!){updateIssueComment(input:{id:$id,body:$body}){issueComment{id}}}",
                            "-f",
                            f"id={comment_id}",
                            "-f",
                            f"body={body}",
                        ]
                    )
                    return
                self._run_gh(
                    [
                        "gh",
                        "api",
                        "-X",
                        "PATCH",
                        f"repos/{owner}/{repo}/issues/comments/{comment_id}",
                        "-f",
                        f"body={body}",
                    ]
                )
                return
            raise ValueError("GitHub token이 설정되어 있지 않습니다.")

        url = f"https://api.github.com/repos/{owner}/{repo}/issues/comments/{comment_id}"
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        response = httpx.patch(url, headers=headers, json={"body": body}, timeout=20)
        try:
            response.raise_for_status()
        except Exception:
            if self.use_gh_cli:
                self._run_gh(
                    [
                        "gh",
                        "api",
                        "-X",
                        "PATCH",
                        f"repos/{owner}/{repo}/issues/comments/{comment_id}",
                        "-f",
                        f"body={body}",
                    ]
                )
                return
            raise

    # GitHub 이슈 댓글을 삭제한다.
    def delete_issue_comment(self, owner: str, repo: str, comment_id: int | str) -> None:
        if not self.token:
            if self.use_gh_cli:
                if isinstance(comment_id, str) and not comment_id.isdigit():
                    self._run_gh(
                        [
                            "gh",
                            "api",
                            "graphql",
                            "-f",
                            "query=mutation($id:ID!){deleteIssueComment(input:{id:$id}){clientMutationId}}",
                            "-f",
                            f"id={comment_id}",
                        ]
                    )
                    return
                self._run_gh(
                    [
                        "gh",
                        "api",
                        "-X",
                        "DELETE",
                        f"repos/{owner}/{repo}/issues/comments/{comment_id}",
                    ]
                )
                return
            raise ValueError("GitHub token이 설정되어 있지 않습니다.")

        url = f"https://api.github.com/repos/{owner}/{repo}/issues/comments/{comment_id}"
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        response = httpx.delete(url, headers=headers, timeout=20)
        try:
            response.raise_for_status()
        except Exception:
            if self.use_gh_cli:
                self._run_gh(
                    [
                        "gh",
                        "api",
                        "-X",
                        "DELETE",
                        f"repos/{owner}/{repo}/issues/comments/{comment_id}",
                    ]
                )
                return
            raise

    def get_issue(self, owner: str, repo: str, issue_number: int) -> dict:
        if not self.token:
            if self.use_gh_cli:
                payload = self._run_gh_json(
                    [
                        "gh",
                        "issue",
                        "view",
                        str(issue_number),
                        "--repo",
                        self._repo(owner, repo),
                        "--json",
                        "number,title,body,url,labels",
                    ]
                )
                return self._normalize_issue(payload)
            raise ValueError("GitHub token이 설정되어 있지 않습니다.")

        url = f"https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}"
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        response = httpx.get(url, headers=headers, timeout=20)
        try:
            response.raise_for_status()
            return response.json()
        except Exception:
            if self.use_gh_cli:
                payload = self._run_gh_json(
                    [
                        "gh",
                        "issue",
                        "view",
                        str(issue_number),
                        "--repo",
                        self._repo(owner, repo),
                        "--json",
                        "number,title,body,url,labels",
                    ]
                )
                return self._normalize_issue(payload)
            raise

    def list_issues(self, owner: str, repo: str, state: str = "open") -> list[dict]:
        if not self.token:
            if self.use_gh_cli:
                payload = self._run_gh_json(
                    [
                        "gh",
                        "issue",
                        "list",
                        "--repo",
                        self._repo(owner, repo),
                        "--state",
                        state,
                        "--limit",
                        "200",
                        "--json",
                        "number,title,body,url,labels",
                    ]
                )
                return [self._normalize_issue(item) for item in payload]
            raise ValueError("GitHub token이 설정되어 있지 않습니다.")

        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        issues: list[dict] = []
        page = 1
        while True:
            url = f"https://api.github.com/repos/{owner}/{repo}/issues"
            response = httpx.get(
                url,
                headers=headers,
                params={"state": state, "per_page": 100, "page": page},
                timeout=20,
            )
            try:
                response.raise_for_status()
            except Exception:
                if self.use_gh_cli:
                    payload = self._run_gh_json(
                        [
                            "gh",
                            "issue",
                            "list",
                            "--repo",
                            self._repo(owner, repo),
                            "--state",
                            state,
                            "--limit",
                            "200",
                            "--json",
                            "number,title,body,url,labels",
                        ]
                    )
                    return [self._normalize_issue(item) for item in payload]
                raise
            payload = response.json()
            chunk = [item for item in payload if "pull_request" not in item]
            issues.extend(chunk)
            if len(payload) < 100:
                break
            page += 1
        return issues

    def list_issue_comments(self, owner: str, repo: str, issue_number: int) -> list[dict]:
        if not self.token:
            if self.use_gh_cli:
                payload = self._run_gh_json(
                    [
                        "gh",
                        "issue",
                        "view",
                        str(issue_number),
                        "--repo",
                        self._repo(owner, repo),
                        "--comments",
                        "--json",
                        "comments",
                    ]
                )
                return payload.get("comments", []) if isinstance(payload, dict) else []
            raise ValueError("GitHub token이 설정되어 있지 않습니다.")

        url = f"https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}/comments"
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        response = httpx.get(url, headers=headers, params={"per_page": 100}, timeout=20)
        try:
            response.raise_for_status()
            return response.json()
        except Exception:
            if self.use_gh_cli:
                payload = self._run_gh_json(
                    [
                        "gh",
                        "issue",
                        "view",
                        str(issue_number),
                        "--repo",
                        self._repo(owner, repo),
                        "--comments",
                        "--json",
                        "comments",
                    ]
                )
                return payload.get("comments", []) if isinstance(payload, dict) else []
            raise
