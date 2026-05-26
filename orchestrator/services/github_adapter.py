import httpx


class GitHubAdapter:
    def __init__(self, token: str | None):
        self.token = token

    def is_configured(self) -> bool:
        return bool(self.token)

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
