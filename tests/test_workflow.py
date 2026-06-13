import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.workflows.state import PRReviewState
from app.workflows.pr_workflow import (
    validate_event_node, 
    fetch_pr_metadata_node, 
    fetch_changed_files_node,
    review_code_node,
    generate_findings_node,
    generate_summary_node,
    post_comments_node
)
from app.models.schemas import LineFinding, PRSummaryResponse


@pytest.mark.asyncio
async def test_validate_event_node_success():
    payload = {
        "action": "opened",
        "pull_request": {
            "number": 42,
            "title": "Review me",
            "head": {"sha": "headsha"},
            "base": {"sha": "basesha"},
            "user": {"login": "coder"},
            "html_url": "https://github.com/owner/repo/pull/42"
        },
        "repository": {
            "name": "repo",
            "full_name": "owner/repo"
        }
    }
    state = {"webhook_payload": payload}
    
    with patch("app.workflows.pr_workflow.SessionLocal") as mock_db:
        mock_db_session = MagicMock()
        mock_db.return_value = mock_db_session
        
        result = await validate_event_node(state)
        
        assert result["repo_full_name"] == "owner/repo"
        assert result["pr_number"] == 42
        assert result["status"] == "active"


@pytest.mark.asyncio
async def test_fetch_pr_metadata_node():
    state = {
        "repo_full_name": "owner/repo",
        "pr_number": 42,
        "status": "active"
    }
    
    mock_pr = {"title": "Refreshed PR Title", "body": "PR description", "user": {"login": "coder"}}
    mock_files = [{"filename": "main.py", "patch": "@@ -1 +1 @@"}]
    
    with patch("app.workflows.pr_workflow.github_service.fetch_pr_info", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = (mock_pr, mock_files)
        
        result = await fetch_pr_metadata_node(state)
        
        assert result["pr_title"] == "Refreshed PR Title"
        assert result["changed_files"] == mock_files


@pytest.mark.asyncio
async def test_review_code_node():
    state = {
        "changed_files": [{"filename": "app.py", "patch": "@@ -1 +1 @@"}],
        "diff_map": {"app.py": MagicMock()},
        "rag_contexts": {"app.py": "conventions"},
        "status": "active"
    }
    
    mock_findings = [LineFinding(severity="medium", category="performance", file="app.py", line=1, issue="slow", recommendation="fix")]
    
    with patch("app.workflows.pr_workflow.gemini_service.review_file_diff", new_callable=AsyncMock) as mock_review:
        mock_review.return_value = mock_findings
        
        result = await review_code_node(state)
        
        assert len(result["raw_findings"]) == 1
        assert result["raw_findings"][0].severity == "medium"


@pytest.mark.asyncio
async def test_fetch_changed_files_node_filtering():
    state = {
        "changed_files": [
            {"filename": "app/main.py", "patch": "@@ -1 +1 @@"},
            {"filename": "venv/lib/python3.12/site-packages/httpx/__init__.py", "patch": "@@ -1 +1 @@"},
            {"filename": "package-lock.json", "patch": "@@ -1 +1 @@"},
            {"filename": "data/reviews.db", "patch": "@@ -1 +1 @@"},
            {"filename": "images/screenshot.png", "patch": "@@ -1 +1 @@"},
        ],
        "status": "active",
        "errors": []
    }
    
    with patch("app.workflows.pr_workflow.github_service.get_pr_diff_map", new_callable=AsyncMock) as mock_diff_map:
        mock_diff_map.return_value = {"app/main.py": MagicMock()}
        
        result = await fetch_changed_files_node(state)
        
        # Ensure only the non-excluded file was processed
        mock_diff_map.assert_called_once()
        called_args = mock_diff_map.call_args[0][0]
        assert len(called_args) == 1
        assert called_args[0]["filename"] == "app/main.py"
        
        # Ensure state contains filtered list
        assert len(result["changed_files"]) == 1
        assert result["changed_files"][0]["filename"] == "app/main.py"
