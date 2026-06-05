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

    # gh CLI를 실행하고 원문 출력을 반환한다.
    def _run_gh_text(self, command: list[str]) -> str:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
        if completed.returncode != 0:
            raise RuntimeError((completed.stderr or completed.stdout or f"exit_code={completed.returncode}").strip())
        return completed.stdout

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

    # GitHub Project의 Status 필드를 지정한 상태명으로 이동한다.
    def move_issue_project_status(
        self,
        owner: str,
        repo: str,
        issue_number: int,
        project_number: int,
        status_name: str,
    ) -> None:
        if not self.token and not self.use_gh_cli:
            raise ValueError("GitHub token 또는 gh CLI 인증이 필요합니다.")

        project = self._get_user_project_status_field(owner, project_number)
        status_field = project["status_field"]
        option_id = self._status_option_id(status_field, status_name)
        item_id = self._get_project_item_id(owner, repo, issue_number, project["id"])
        self._update_project_status(project["id"], item_id, status_field["id"], option_id)

    # 사용자 GitHub Project에서 Status single select 필드를 찾는다.
    def _get_user_project_status_field(self, owner: str, project_number: int) -> dict:
        query = """
        query($owner:String!, $number:Int!) {
          user(login:$owner) {
            projectV2(number:$number) {
              id
              fields(first:50) {
                nodes {
                  ... on ProjectV2FieldCommon { id name }
                  ... on ProjectV2SingleSelectField { id name options { id name } }
                }
              }
            }
          }
        }
        """
        payload = self._graphql(query, {"owner": owner, "number": project_number})
        project = payload["data"]["user"]["projectV2"]
        fields = project["fields"]["nodes"]
        status_field = next((field for field in fields if field and field.get("name") == "Status"), None)
        if not status_field:
            raise RuntimeError("GitHub Project에서 Status 필드를 찾을 수 없습니다.")
        return {"id": project["id"], "status_field": status_field}

    # Status 필드 옵션 중 이동 대상 상태의 option id를 찾는다.
    def _status_option_id(self, status_field: dict, status_name: str) -> str:
        for option in status_field.get("options") or []:
            if option.get("name") == status_name:
                return option["id"]
        options = ", ".join(option.get("name", "") for option in status_field.get("options") or [])
        raise RuntimeError(f"GitHub Project Status 옵션을 찾을 수 없습니다: target={status_name}, options={options}")

    # 이슈가 프로젝트 안에서 가진 item id를 찾는다.
    def _get_project_item_id(self, owner: str, repo: str, issue_number: int, project_id: str) -> str:
        query = """
        query($owner:String!, $repo:String!, $issueNumber:Int!) {
          repository(owner:$owner, name:$repo) {
            issue(number:$issueNumber) {
              projectItems(first:50) {
                nodes {
                  id
                  project { id }
                }
              }
            }
          }
        }
        """
        payload = self._graphql(query, {"owner": owner, "repo": repo, "issueNumber": issue_number})
        items = payload["data"]["repository"]["issue"]["projectItems"]["nodes"]
        for item in items:
            if item and item.get("project", {}).get("id") == project_id:
                return item["id"]
        raise RuntimeError(f"이슈 #{issue_number}의 GitHub Project item을 찾을 수 없습니다.")

    # Project item의 Status 값을 업데이트한다.
    def _update_project_status(self, project_id: str, item_id: str, field_id: str, option_id: str) -> None:
        query = """
        mutation($projectId:ID!, $itemId:ID!, $fieldId:ID!, $optionId:String!) {
          updateProjectV2ItemFieldValue(input:{
            projectId:$projectId,
            itemId:$itemId,
            fieldId:$fieldId,
            value:{singleSelectOptionId:$optionId}
          }) {
            projectV2Item { id }
          }
        }
        """
        self._graphql(
            query,
            {
                "projectId": project_id,
                "itemId": item_id,
                "fieldId": field_id,
                "optionId": option_id,
            },
        )

    # GitHub GraphQL API를 token 또는 gh CLI로 호출한다.
    def _graphql(self, query: str, variables: dict) -> dict:
        if self.token:
            response = httpx.post(
                "https://api.github.com/graphql",
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Accept": "application/vnd.github+json",
                },
                json={"query": query, "variables": variables},
                timeout=20,
            )
            response.raise_for_status()
            payload = response.json()
        elif self.use_gh_cli:
            command = ["gh", "api", "graphql", "-f", f"query={query}"]
            for key, value in variables.items():
                flag = "-F" if isinstance(value, int) else "-f"
                command.extend([flag, f"{key}={value}"])
            payload = json.loads(self._run_gh_text(command) or "{}")
        else:
            raise ValueError("GitHub token 또는 gh CLI 인증이 필요합니다.")

        if payload.get("errors"):
            raise RuntimeError(json.dumps(payload["errors"], ensure_ascii=False))
        return payload

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
