import httpx


class GitHubAdapter:
    def __init__(self, token: str | None):
        self.token = token

    def is_configured(self) -> bool:
        return bool(self.token)

    def create_issue(
        self,
        owner: str,
        repo: str,
        title: str,
        body: str,
        labels: list[str] | None = None,
    ) -> dict:
        if not self.token:
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
        response.raise_for_status()
        return response.json()

    def create_issue_comment(
        self,
        owner: str,
        repo: str,
        issue_number: int,
        body: str,
    ) -> None:
        if not self.token:
            raise ValueError("GitHub token이 설정되어 있지 않습니다.")

        url = f"https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}/comments"
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        response = httpx.post(url, headers=headers, json={"body": body}, timeout=20)
        response.raise_for_status()

    def get_issue(self, owner: str, repo: str, issue_number: int) -> dict:
        if not self.token:
            raise ValueError("GitHub token이 설정되어 있지 않습니다.")

        url = f"https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}"
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        response = httpx.get(url, headers=headers, timeout=20)
        response.raise_for_status()
        return response.json()

    def list_issues(self, owner: str, repo: str, state: str = "open") -> list[dict]:
        if not self.token:
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
            response.raise_for_status()
            payload = response.json()
            chunk = [item for item in payload if "pull_request" not in item]
            issues.extend(chunk)
            if len(payload) < 100:
                break
            page += 1
        return issues

    def list_issue_comments(self, owner: str, repo: str, issue_number: int) -> list[dict]:
        if not self.token:
            raise ValueError("GitHub token이 설정되어 있지 않습니다.")

        url = f"https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}/comments"
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        response = httpx.get(url, headers=headers, params={"per_page": 100}, timeout=20)
        response.raise_for_status()
        return response.json()
