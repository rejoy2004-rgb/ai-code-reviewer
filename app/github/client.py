import os
import hmac
import hashlib
import logging
from typing import List, Dict, Any, Optional
import httpx
from app.config.settings import settings
from app.utils.rate_limiter import async_retry

logger = logging.getLogger("app.github_client")


class GitHubAPIException(Exception):
    """Custom exception for GitHub API errors."""
    def __init__(self, status_code: int, response_text: str):
        self.status_code = status_code
        self.response_text = response_text
        super().__init__(f"GitHub API Error {status_code}: {response_text}")


class GitHubClient:
    def __init__(self, token: Optional[str] = None):
        self.token = token or settings.GITHUB_TOKEN or os.environ.get("GITHUB_TOKEN", "")
        self.base_url = "https://api.github.com"
        self.headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "FastAPI-PR-Reviewer-Agent"
        }

    @staticmethod
    def verify_webhook_signature(payload_body: bytes, signature_header: Optional[str], secret: str) -> bool:
        """
        Validates GitHub webhook signatures using HMAC SHA-256.
        """
        if not signature_header:
            logger.error("Missing signature header.")
            return False
            
        if not signature_header.startswith("sha256="):
            logger.error("Signature header is not sha256.")
            return False

        # Extract signature digest
        signature = signature_header.split("sha256=")[1]
        
        # Calculate HMAC SHA-256
        mac = hmac.new(secret.encode("utf-8"), msg=payload_body, digestmod=hashlib.sha256)
        expected_signature = mac.hexdigest()

        return hmac.compare_digest(expected_signature, signature)

    @async_retry(max_retries=3, initial_delay=2.0, retryable_exceptions=(GitHubAPIException, httpx.HTTPError))
    async def _request(self, method: str, endpoint: str, **kwargs) -> Any:
        """Executes an async HTTP request to the GitHub API."""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.request(method, url, headers=self.headers, **kwargs)
                
                # Check for rate limit issues
                remaining = response.headers.get("X-RateLimit-Remaining")
                reset_time = response.headers.get("X-RateLimit-Reset")
                logger.debug(f"GitHub API limits: remaining={remaining}, reset={reset_time}")
                
                if response.status_code == 403 and remaining == "0":
                    logger.warning(f"GitHub rate limit exceeded. Reset time: {reset_time}")
                    raise GitHubAPIException(429, "GitHub rate limit exceeded")

                if response.status_code >= 400:
                    raise GitHubAPIException(response.status_code, response.text)
                
                # If content type is JSON, return parsed dict
                if "application/json" in response.headers.get("content-type", ""):
                    return response.json()
                return response.text
            except httpx.HTTPError as e:
                logger.error(f"HTTP connection error: {e}")
                raise e

    async def get_pull_request(self, repo_owner: str, repo_name: str, pr_number: int) -> Dict[str, Any]:
        """Fetches metadata for a pull request."""
        endpoint = f"repos/{repo_owner}/{repo_name}/pulls/{pr_number}"
        return await self._request("GET", endpoint)

    async def get_changed_files(self, repo_owner: str, repo_name: str, pr_number: int) -> List[Dict[str, Any]]:
        """Fetches the list of files modified in a pull request."""
        # Note: GitHub lists up to 300 files. For extremely large PRs, pagination is required.
        # We fetch the first page. For PR reviews, 100 files is usually the practical limit.
        endpoint = f"repos/{repo_owner}/{repo_name}/pulls/{pr_number}/files?per_page=100"
        return await self._request("GET", endpoint)

    async def create_review_comment(
        self,
        repo_owner: str,
        repo_name: str,
        pr_number: int,
        commit_id: str,
        file_path: str,
        line: int,
        body: str,
        side: str = "RIGHT"
    ) -> Dict[str, Any]:
        """
        Creates an inline review comment on a specific line of a file in the pull request.
        """
        endpoint = f"repos/{repo_owner}/{repo_name}/pulls/{pr_number}/comments"
        payload = {
            "body": body,
            "commit_id": commit_id,
            "path": file_path,
            "line": line,
            "side": side
        }
        return await self._request("POST", endpoint, json=payload)

    async def create_summary_comment(self, repo_owner: str, repo_name: str, pr_number: int, body: str) -> Dict[str, Any]:
        """
        Creates a high-level comment on the pull request (which is treated as an issue by GitHub).
        """
        endpoint = f"repos/{repo_owner}/{repo_name}/issues/{pr_number}/comments"
        payload = {"body": body}
        return await self._request("POST", endpoint, json=payload)

    async def get_comments(self, repo_owner: str, repo_name: str, pr_number: int) -> List[Dict[str, Any]]:
        """Fetches existing review comments for a pull request."""
        endpoint = f"repos/{repo_owner}/{repo_name}/pulls/{pr_number}/comments"
        return await self._request("GET", endpoint)

    async def get_issue_comments(self, repo_owner: str, repo_name: str, pr_number: int) -> List[Dict[str, Any]]:
        """Fetches issue (general) comments for a pull request."""
        endpoint = f"repos/{repo_owner}/{repo_name}/issues/{pr_number}/comments"
        return await self._request("GET", endpoint)
