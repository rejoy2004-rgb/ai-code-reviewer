import pytest
from unittest.mock import AsyncMock, patch
from app.github.client import GitHubClient, GitHubAPIException


@pytest.mark.asyncio
async def test_github_client_get_pr():
    client = GitHubClient(token="mock-token")
    
    mock_response = {
        "number": 1,
        "title": "A mock PR",
        "head": {"sha": "headsha"},
        "base": {"sha": "basesha"}
    }
    
    # Mock the internal request method
    with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = mock_response
        
        pr = await client.get_pull_request("owner", "repo", 1)
        
        assert pr["number"] == 1
        assert pr["title"] == "A mock PR"
        mock_req.assert_called_once_with("GET", "repos/owner/repo/pulls/1")


@pytest.mark.asyncio
async def test_github_client_create_comment():
    client = GitHubClient(token="mock-token")
    
    with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = {"id": 123, "body": "looks good"}
        
        res = await client.create_review_comment(
            repo_owner="owner",
            repo_name="repo",
            pr_number=1,
            commit_id="headsha",
            file_path="main.py",
            line=10,
            body="looks good"
        )
        
        assert res["id"] == 123
        mock_req.assert_called_once_with(
            "POST", 
            "repos/owner/repo/pulls/1/comments", 
            json={
                "body": "looks good",
                "commit_id": "headsha",
                "path": "main.py",
                "line": 10,
                "side": "RIGHT"
            }
        )
