import logging
import asyncio
from fastapi import APIRouter, Request, Header, HTTPException, BackgroundTasks, Depends
from sqlalchemy.orm import Session
from typing import Optional

from app.config.settings import settings
from app.github.client import GitHubClient
from app.workflows.pr_workflow import review_workflow
from app.services.analytics_service import AnalyticsService
from app.db.session import get_db

logger = logging.getLogger("app.webhooks")
router = APIRouter()


async def run_review_workflow(payload: dict):
    """Asynchronous background task to run the LangGraph PR review."""
    logger.info("Executing LangGraph review workflow in background...")
    initial_state = {
        "webhook_payload": payload,
        "errors": [],
        "status": "pending"
    }
    try:
        await review_workflow.ainvoke(initial_state)
        logger.info("LangGraph review workflow finished execution successfully.")
    except Exception as e:
        logger.error(f"LangGraph execution crashed in background: {e}")


@router.post("/github")
async def github_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_hub_signature_256: Optional[str] = Header(None),
    x_github_event: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    """
    Receives and validates GitHub Webhook events.
    Triggers code reviews for PR actions, or updates developer feedback database on comments.
    """
    # Read raw body bytes for HMAC validation
    body_bytes = await request.body()
    
    # Validate webhook signature
    is_valid = GitHubClient.verify_webhook_signature(
        payload_body=body_bytes,
        signature_header=x_hub_signature_256,
        secret=settings.GITHUB_WEBHOOK_SECRET
    )
    
    if not is_valid:
        logger.warning("Invalid webhook signature received.")
        raise HTTPException(status_code=401, detail="Invalid signature")

    # Parse payload json
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    logger.info(f"Received GitHub webhook event: '{x_github_event}'")

    # 1. Handle Pull Request events (triggers reviews)
    if x_github_event == "pull_request":
        action = payload.get("action")
        if action in ("opened", "synchronize", "reopened"):
            background_tasks.add_task(run_review_workflow, payload)
            return {"message": "Review workflow scheduled in background", "action": action}
        else:
            return {"message": f"Ignored pull request action '{action}'"}

    # 2. Handle Pull Request Review Comments (developer feedback loop)
    elif x_github_event in ("pull_request_review_comment", "issue_comment"):
        action = payload.get("action")
        comment = payload.get("comment")
        repo = payload.get("repository", {})
        issue = payload.get("issue")
        pull_request = payload.get("pull_request")

        # Get PR number (issue_comment contains 'issue', pull_request_review_comment contains 'pull_request')
        pr_number = None
        if pull_request:
            pr_number = pull_request.get("number")
        elif issue and issue.get("pull_request"):
            pr_number = issue.get("number")

        if action == "created" and comment and pr_number and repo:
            comment_author = comment.get("user", {}).get("login")
            comment_body = comment.get("body", "")
            comment_id = comment.get("id")
            repo_name = repo.get("full_name")

            # Check if this comment is from a developer, not the bot itself (avoid self-loops)
            # We assume if the author doesn't have '[bot]' or similar name, it's a developer reply.
            if "bot" not in comment_author.lower():
                logger.info(f"Feedback Loop: Recorded comment from {comment_author} on PR #{pr_number}")
                AnalyticsService.record_feedback(
                    db=db,
                    repo_name=repo_name,
                    pr_number=pr_number,
                    comment_id=str(comment_id),
                    body=comment_body
                )
                return {"message": "Feedback recorded"}

    return {"message": f"Webhook event '{x_github_event}' acknowledged"}
