from __future__ import annotations

from dataclasses import dataclass
import io
import json
import os
from typing import Any, Protocol
from urllib import error, request
import zipfile


@dataclass(slots=True)
class WorkflowRunRef:
    run_id: str
    status: str
    conclusion: str | None = None
    commit_sha: str | None = None
    url: str | None = None


@dataclass(slots=True)
class WorkflowJobRef:
    job_id: str
    name: str
    status: str
    conclusion: str | None = None


@dataclass(slots=True)
class GitHubDeliveryResult:
    repository_full_name: str
    repository_url: str
    branch: str
    commit_sha: str
    created_repo: bool = False


class GitHubProvider(Protocol):
    def create_repo(self, owner: str, repo: str) -> str: ...
    def commit_files(
        self,
        repository_full_name: str,
        files: dict[str, str],
        message: str = "Add generated NL2Service scaffold",
    ) -> GitHubDeliveryResult: ...
    def get_workflow_runs(self, owner: str, repo: str) -> list[WorkflowRunRef]: ...
    def get_workflow_run_for_commit(self, owner: str, repo: str, commit_sha: str) -> WorkflowRunRef | None: ...
    def get_workflow_jobs(self, owner: str, repo: str, run_id: str) -> list[WorkflowJobRef]: ...
    def get_workflow_logs(self, owner: str, repo: str, run_id: str) -> str: ...


class GitHubAPIError(RuntimeError):
    pass


class GitHubApiProvider:
    def __init__(
        self,
        token: str | None = None,
        api_base_url: str | None = None,
        server_url: str | None = None,
    ) -> None:
        self.token = token or os.getenv("GITHUB_TOKEN")
        self.api_base_url = (api_base_url or os.getenv("GITHUB_API_URL") or "https://api.github.com").rstrip("/")
        self.server_url = (server_url or os.getenv("GITHUB_SERVER_URL") or "https://github.com").rstrip("/")

    def create_repo(self, owner: str, repo: str) -> str:
        self._require_token()
        payload = {"name": repo, "private": False, "auto_init": True}
        org_error: GitHubAPIError | None = None
        if owner:
            try:
                response = self._request_json("POST", f"/orgs/{owner}/repos", payload)
                return str(response["html_url"])
            except GitHubAPIError as exc:
                org_error = exc
        try:
            response = self._request_json("POST", "/user/repos", payload)
            return str(response["html_url"])
        except GitHubAPIError:
            if org_error is not None:
                raise org_error
            raise

    def commit_files(
        self,
        repository_full_name: str,
        files: dict[str, str],
        message: str = "Add generated NL2Service scaffold",
    ) -> GitHubDeliveryResult:
        repo_meta = self._request_json("GET", f"/repos/{repository_full_name}")
        default_branch = str(repo_meta["default_branch"])
        head_ref = self._request_json("GET", f"/repos/{repository_full_name}/git/ref/heads/{default_branch}")
        parent_sha = str(head_ref["object"]["sha"])
        head_commit = self._request_json("GET", f"/repos/{repository_full_name}/git/commits/{parent_sha}")
        base_tree_sha = str(head_commit["tree"]["sha"])

        tree_elements: list[dict[str, Any]] = []
        for path, content in files.items():
            blob = self._request_json(
                "POST",
                f"/repos/{repository_full_name}/git/blobs",
                {"content": content, "encoding": "utf-8"},
            )
            tree_elements.append({"path": path, "mode": "100644", "type": "blob", "sha": str(blob["sha"])})

        tree = self._request_json(
            "POST",
            f"/repos/{repository_full_name}/git/trees",
            {"base_tree": base_tree_sha, "tree": tree_elements},
        )
        commit = self._request_json(
            "POST",
            f"/repos/{repository_full_name}/git/commits",
            {"message": message, "tree": tree["sha"], "parents": [parent_sha]},
        )
        self._request_json(
            "PATCH",
            f"/repos/{repository_full_name}/git/refs/heads/{default_branch}",
            {"sha": commit["sha"], "force": False},
        )
        return GitHubDeliveryResult(
            repository_full_name=repository_full_name,
            repository_url=str(repo_meta["html_url"]),
            branch=default_branch,
            commit_sha=str(commit["sha"]),
            created_repo=False,
        )

    def get_workflow_runs(self, owner: str, repo: str) -> list[WorkflowRunRef]:
        payload = self._request_json("GET", f"/repos/{owner}/{repo}/actions/runs?per_page=10")
        runs: list[WorkflowRunRef] = []
        for item in payload.get("workflow_runs", []):
            runs.append(
                WorkflowRunRef(
                    run_id=str(item["id"]),
                    status=str(item.get("status", "unknown")),
                    conclusion=item.get("conclusion"),
                    commit_sha=item.get("head_sha"),
                    url=item.get("html_url"),
                )
            )
        return runs

    def get_workflow_run_for_commit(self, owner: str, repo: str, commit_sha: str) -> WorkflowRunRef | None:
        payload = self._request_json(
            "GET", f"/repos/{owner}/{repo}/actions/runs?head_sha={commit_sha}&per_page=10"
        )
        for item in payload.get("workflow_runs", []):
            if str(item.get("head_sha")) != commit_sha:
                continue
            return WorkflowRunRef(
                run_id=str(item["id"]),
                status=str(item.get("status", "unknown")),
                conclusion=item.get("conclusion"),
                commit_sha=item.get("head_sha"),
                url=item.get("html_url"),
            )
        return None

    def get_workflow_jobs(self, owner: str, repo: str, run_id: str) -> list[WorkflowJobRef]:
        payload = self._request_json("GET", f"/repos/{owner}/{repo}/actions/runs/{run_id}/jobs?per_page=100")
        return [
            WorkflowJobRef(
                job_id=str(item["id"]),
                name=str(item.get("name", "unknown")),
                status=str(item.get("status", "unknown")),
                conclusion=item.get("conclusion"),
            )
            for item in payload.get("jobs", [])
        ]

    def get_workflow_logs(self, owner: str, repo: str, run_id: str) -> str:
        self._require_token()
        req = request.Request(
            f"{self.api_base_url}/repos/{owner}/{repo}/actions/runs/{run_id}/logs",
            headers=self._headers(),
            method="GET",
        )
        try:
            with request.urlopen(req) as response:
                archive = response.read()
                with zipfile.ZipFile(io.BytesIO(archive)) as logs:
                    blocks: list[str] = []
                    for name in sorted(logs.namelist()):
                        if name.endswith("/"):
                            continue
                        content = logs.read(name).decode("utf-8", errors="replace")
                        blocks.append(f"LOG FILE: {name}\n{content}")
                    return "\n\n".join(blocks)
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise GitHubAPIError(f"GitHub API request failed ({exc.code}): {body}") from exc
        except zipfile.BadZipFile as exc:
            raise GitHubAPIError("GitHub Actions logs response was not a valid ZIP archive.") from exc

    def _request_json(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        self._require_token()
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        req = request.Request(
            f"{self.api_base_url}{path}",
            data=data,
            headers=self._headers(),
            method=method,
        )
        try:
            with request.urlopen(req) as response:
                raw = response.read().decode("utf-8")
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise GitHubAPIError(f"GitHub API request failed ({exc.code}): {body}") from exc
        return json.loads(raw) if raw else {}

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "nl2service",
            "Content-Type": "application/json",
        }

    def _require_token(self) -> None:
        if not self.token:
            raise GitHubAPIError("GITHUB_TOKEN is required for GitHub delivery.")
