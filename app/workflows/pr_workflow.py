import asyncio
import logging
from typing import Dict, Any, List, Literal
from langgraph.graph import StateGraph, END

from app.workflows.state import PRReviewState
from app.services.github_service import GitHubService
from app.services.gemini_service import GeminiService
from app.services.slack_service import SlackService
from app.rag.retriever import RepositoryRetriever
from app.db.session import SessionLocal
from app.models.database import ReviewRecord, ReviewFinding, init_db

logger = logging.getLogger("app.pr_workflow")

# Ensure database is initialized before execution
init_db()

# Services
github_service = GitHubService()
gemini_service = GeminiService()
slack_service = SlackService()
retriever = RepositoryRetriever()


# --- Node Implementations ---

async def validate_event_node(state: PRReviewState) -> Dict[str, Any]:
    """
    Validates webhook payload to ensure it is a relevant PR action.
    Creates a pending review record in the local database.
    """
    logger.info("Node: validate_event")
    payload = state.get("webhook_payload", {})
    
    action = payload.get("action")
    pr_data = payload.get("pull_request")
    repo_data = payload.get("repository")
    
    if not pr_data or not repo_data:
        logger.warning("Invalid webhook payload. Missing pull_request or repository.")
        return {"status": "failed", "errors": ["Missing pull_request or repository payload"]}

    allowed_actions = {"opened", "synchronize", "reopened"}
    if action not in allowed_actions:
        logger.info(f"Ignored action '{action}'. Review only triggered for: {allowed_actions}")
        return {"status": "skipped", "errors": [f"Action '{action}' is ignored"]}

    repo_full_name = repo_data.get("full_name")
    pr_number = pr_data.get("number")
    commit_sha = pr_data.get("head", {}).get("sha")

    # Create a database record for this review run
    db = SessionLocal()
    try:
        record = ReviewRecord(
            repo_name=repo_full_name,
            pr_number=pr_number,
            commit_sha=commit_sha,
            status="processing"
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        db_id = record.id
    except Exception as e:
        logger.error(f"Failed to write review record to database: {e}")
        db_id = None
    finally:
        db.close()

    return {
        "repo_full_name": repo_full_name,
        "pr_number": pr_number,
        "commit_sha": commit_sha,
        "pr_title": pr_data.get("title", ""),
        "pr_description": pr_data.get("body", ""),
        "pr_author": pr_data.get("user", {}).get("login", ""),
        "pr_html_url": pr_data.get("html_url", ""),
        "db_record_id": db_id,
        "status": "active",
        "errors": []
    }


async def fetch_pr_metadata_node(state: PRReviewState) -> Dict[str, Any]:
    """
    Refreshes PR metadata from the GitHub REST API to ensure we have fresh data.
    """
    logger.info("Node: fetch_pr_metadata")
    if state.get("status") in ("failed", "skipped"):
        return {}

    try:
        pr_metadata, changed_files = await github_service.fetch_pr_info(
            state["repo_full_name"], state["pr_number"]
        )
        return {
            "pr_title": pr_metadata.get("title") or state.get("pr_title") or "",
            "pr_description": pr_metadata.get("body") or state.get("pr_description") or "",
            "pr_author": pr_metadata.get("user", {}).get("login") or state.get("pr_author") or "",
            "pr_html_url": pr_metadata.get("html_url") or state.get("pr_html_url") or "",
            "commit_sha": pr_metadata.get("head", {}).get("sha") or state.get("commit_sha") or "",
            "changed_files": changed_files
        }
    except Exception as e:
        logger.error(f"Error fetching PR metadata: {e}")
        return {"status": "failed", "errors": state.get("errors", []) + [f"Fetch PR metadata failed: {str(e)}"]}


def should_exclude_file(filename: str) -> bool:
    """
    Returns True if the file should be excluded from AI review (e.g. dependencies, lock files, binary files, or caches).
    """
    # Normalize path separators
    filename = filename.replace("\\", "/").lower()
    
    # Common dependency, cache, and build directories
    exclude_dirs = [
        "venv/",
        ".venv/",
        "env/",
        ".env/",
        "node_modules/",
        "bower_components/",
        "dist/",
        "build/",
        "target/",
        "out/",
        "bin/",
        "obj/",
        "__pycache__/",
        ".pytest_cache/",
        ".coverage",
        "htmlcov/",
        ".git/",
        ".github/",
        ".vscode/",
        ".idea/",
        "data/chromadb/",
        "data/db/",
    ]
    
    # Check if the filename starts with or contains any of the exclude directories
    for d in exclude_dirs:
        if filename.startswith(d) or f"/{d}" in filename:
            return True
            
    # File name patterns or exact matches
    exclude_files = {
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "poetry.lock",
        "pipfile.lock",
        "composer.lock",
        "cargo.lock",
        "gemfile.lock",
        ".env",
        ".env.local",
        ".env.development",
        ".env.test",
        ".env.production",
    }
    
    # Check exact match on basename
    basename = filename.split("/")[-1]
    if basename in exclude_files:
        return True
        
    # File extensions to exclude (binaries, database files, images, etc.)
    exclude_extensions = {
        # Databases & Binary data
        ".db", ".sqlite", ".sqlite3", ".bin", ".dat", ".pkl", ".joblib",
        # Images
        ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".webp", ".pdf",
        # Zip/tar archives
        ".zip", ".tar", ".gz", ".tgz", ".rar", ".7z",
        # Fonts
        ".woff", ".woff2", ".ttf", ".eot", ".otf",
        # Local state/cache/compiled
        ".pyc", ".pyo", ".pyd", ".class", ".o", ".a", ".so", ".dll", ".exe"
    }
    
    # Check extension match
    if any(filename.endswith(ext) for ext in exclude_extensions):
        return True
        
    return False


async def fetch_changed_files_node(state: PRReviewState) -> Dict[str, Any]:
    """
    Parses the patches from changed files and maps diff offsets.
    """
    logger.info("Node: fetch_changed_files")
    if state.get("status") in ("failed", "skipped"):
        return {}

    try:
        changed_files = state.get("changed_files", [])
        
        # Filter files to exclude dependencies, lock files, binary/data files, and caches
        filtered_files = []
        excluded_count = 0
        for f in changed_files:
            filename = f.get("filename", "")
            if should_exclude_file(filename):
                excluded_count += 1
            else:
                filtered_files.append(f)
                
        if excluded_count > 0:
            logger.info(f"Filtered out {excluded_count} dependency/binary/cache/lock files from review.")

        diff_map = await github_service.get_pr_diff_map(filtered_files)
        logger.info(f"Parsed diffs for {len(diff_map)} files.")
        return {"diff_map": diff_map, "changed_files": filtered_files}
    except Exception as e:
        logger.error(f"Error parsing file diffs: {e}")
        return {"status": "failed", "errors": state.get("errors", []) + [f"Fetch changed files failed: {str(e)}"]}


async def retrieve_repository_context_node(state: PRReviewState) -> Dict[str, Any]:
    """
    Queries ChromaDB vector index to pull code reference conventions for modified files.
    """
    logger.info("Node: retrieve_repository_context")
    if state.get("status") in ("failed", "skipped"):
        return {}

    try:
        repo_name = state["repo_full_name"]
        diff_map = state["diff_map"]
        rag_contexts = {}

        # Query vector database for modified files to extract style conventions
        for file_path, parsed_diff in diff_map.items():
            # Extract clean patch lines
            patch = next((f.get("patch") for f in state["changed_files"] if f.get("filename") == file_path), None)
            if patch:
                logger.info(f"Querying codebase conventions for {file_path}")
                context = await retriever.retrieve_context_for_diff(repo_name, file_path, patch)
                rag_contexts[file_path] = context
            else:
                rag_contexts[file_path] = "No patch available."

        return {"rag_contexts": rag_contexts}
    except Exception as e:
        logger.error(f"Error retrieving repository context: {e}")
        # RAG failure shouldn't crash the entire pipeline, we fall back to empty context
        return {"rag_contexts": {}, "errors": state.get("errors", []) + [f"RAG retrieval skipped: {str(e)}"]}


async def review_code_node(state: PRReviewState) -> Dict[str, Any]:
    """
    Batches modified files and runs reviews in parallel, throttled to respect API limits.
    """
    logger.info("Node: review_code")
    if state.get("status") in ("failed", "skipped"):
        return {}

    try:
        diff_map = state["diff_map"]
        rag_contexts = state.get("rag_contexts", {})
        
        tasks = []
        file_paths = list(diff_map.keys())

        # Review files concurrently with a limit of 2 parallel requests to respect OpenRouter rate limits
        semaphore = asyncio.Semaphore(2)

        async def sem_review(f_path, f_patch, f_context):
            async with semaphore:
                return await gemini_service.review_file_diff(f_path, f_patch, f_context)

        for file_path in file_paths:
            patch = next((f.get("patch") for f in state["changed_files"] if f.get("filename") == file_path), None)
            if patch:
                context = rag_contexts.get(file_path, "")
                tasks.append(
                    sem_review(file_path, patch, context)
                )

        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        all_findings = []
        for idx, res in enumerate(results):
            if isinstance(res, Exception):
                logger.error(f"Gemini failed reviewing {file_paths[idx]}: {res}")
                state.get("errors", []).append(f"File {file_paths[idx]} review failed: {str(res)}")
            else:
                all_findings.extend(res)

        logger.info(f"Aggregated {len(all_findings)} raw findings from Gemini.")
        return {"raw_findings": all_findings}
    except Exception as e:
        logger.error(f"Error executing Gemini reviews: {e}")
        return {"status": "failed", "errors": state.get("errors", []) + [f"Code review execution failed: {str(e)}"]}


async def generate_findings_node(state: PRReviewState) -> Dict[str, Any]:
    """
    Filters findings, checks developer feedback memory to suppress ignored issues.
    """
    logger.info("Node: generate_findings")
    if state.get("status") in ("failed", "skipped"):
        return {}

    raw_findings = state.get("raw_findings", [])
    filtered_findings = []
    
    db = SessionLocal()
    try:
        for finding in raw_findings:
            # Query if a developer disputed a similar finding previously in this repo
            # (Developer Feedback Memory check)
            disputed_count = db.query(ReviewFinding).join(ReviewRecord).filter(
                ReviewRecord.repo_name == state["repo_full_name"],
                ReviewFinding.file_path == finding.file,
                ReviewFinding.category == finding.category,
                ReviewFinding.feedback_status == "disputed"
            ).count()

            if disputed_count > 0:
                # Issue category has been disputed on this file by developers before.
                # In production, we downgrade severity or filter out the issue to avoid annoying the team.
                logger.info(f"Feedback loop: Downgrading disputed finding category '{finding.category}' on '{finding.file}'")
                if finding.severity == "high":
                    finding.severity = "medium"
                elif finding.severity == "medium":
                    finding.severity = "low"
                else:
                    # Ignore low findings that developers consistently dispute
                    continue

            filtered_findings.append(finding)
    except Exception as e:
        logger.error(f"Error checking developer feedback loop: {e}")
        filtered_findings = raw_findings # Fallback to raw findings
    finally:
        db.close()

    logger.info(f"Finalized {len(filtered_findings)} findings after filters.")
    return {"filtered_findings": filtered_findings}


async def generate_summary_node(state: PRReviewState) -> Dict[str, Any]:
    """
    Generates high-level PR overview, scoring, risk assessments, and action items.
    """
    logger.info("Node: generate_summary")
    if state.get("status") in ("failed", "skipped"):
        return {}

    try:
        pr_metadata = {
            "title": state["pr_title"],
            "body": state["pr_description"],
            "user": {"login": state["pr_author"]},
            "head": {"ref": state.get("webhook_payload", {}).get("pull_request", {}).get("head", {}).get("ref", "unknown")},
            "base": {"ref": state.get("webhook_payload", {}).get("pull_request", {}).get("base", {}).get("ref", "unknown")},
            "number": state["pr_number"]
        }
        
        summary_response = await gemini_service.generate_pr_summary(
            pr_metadata, state["filtered_findings"]
        )

        return {
            "score": summary_response.score,
            "risk_score": summary_response.risk_score,
            "confidence_score": summary_response.confidence_score,
            "summary_markdown": summary_response.summary
        }
    except Exception as e:
        logger.error(f"Error generating summary: {e}")
        return {"status": "failed", "errors": state.get("errors", []) + [f"PR summary compilation failed: {str(e)}"]}


async def post_comments_node(state: PRReviewState) -> Dict[str, Any]:
    """
    Submits inline comments and final summary comment as a unified GitHub Review.
    Dispatches Slack notification containing scores.
    """
    logger.info("Node: post_comments")
    if state.get("status") in ("failed", "skipped"):
        return {}

    try:
        findings_dicts = [
            {
                "severity": f.severity,
                "category": f.category,
                "file": f.file,
                "line": f.line,
                "issue": f.issue,
                "recommendation": f.recommendation
            }
            for f in state["filtered_findings"]
        ]

        # Post review atomically to GitHub
        await github_service.submit_pr_review(
            repo_full_name=state["repo_full_name"],
            pr_number=state["pr_number"],
            commit_sha=state["commit_sha"],
            summary=state["summary_markdown"],
            findings=findings_dicts,
            diff_map=state["diff_map"]
        )

        # Send Slack notification
        categories_count = {"security": 0, "performance": 0, "code_quality": 0, "maintainability": 0, "style": 0}
        for f in state["filtered_findings"]:
            if f.category in categories_count:
                categories_count[f.category] += 1

        await slack_service.send_review_notification(
            repo_name=state["repo_full_name"],
            pr_number=state["pr_number"],
            pr_title=state["pr_title"],
            pr_url=state["pr_html_url"],
            pr_author=state["pr_author"],
            score=state["score"],
            risk_score=state["risk_score"],
            confidence_score=state["confidence_score"],
            findings_summary=state["summary_markdown"].split("## ⚠️ Core Issues & Risks")[0], # First section only
            categories_count=categories_count
        )

        return {"status": "completed"}
    except Exception as e:
        logger.error(f"Error posting review comments to GitHub/Slack: {e}")
        return {"status": "failed", "errors": state.get("errors", []) + [f"Post comments action failed: {str(e)}"]}


async def store_review_memory_node(state: PRReviewState) -> Dict[str, Any]:
    """
    Logs outputs to SQLite database and completes review run state.
    """
    logger.info("Node: store_review_memory")
    db_id = state.get("db_record_id")
    if not db_id:
        return {}

    db = SessionLocal()
    try:
        record = db.query(ReviewRecord).filter(ReviewRecord.id == db_id).first()
        if record:
            status = state.get("status", "completed")
            record.status = status
            
            if status == "completed":
                record.score = state.get("score")
                record.risk_score = state.get("risk_score")
                record.confidence_score = state.get("confidence_score")
                record.summary = state.get("summary_markdown")
                
                # Write line-by-line findings to db
                for f in state.get("filtered_findings", []):
                    finding_record = ReviewFinding(
                        review_record_id=db_id,
                        file_path=f.file,
                        line_number=f.line,
                        category=f.category,
                        severity=f.severity,
                        issue_description=f.issue,
                        recommendation=f.recommendation
                    )
                    db.add(finding_record)
            
            db.commit()
            logger.info(f"Database review record {db_id} updated with status: {status}")
    except Exception as e:
        logger.error(f"Error updating SQLite review record: {e}")
    finally:
        db.close()

    return {}


# --- Workflow Graph Compilation ---

def should_continue(state: PRReviewState) -> Literal["fetch_pr_metadata", "store_review_memory"]:
    """Conditional edge checks for pipeline execution status."""
    if state.get("status") in ("failed", "skipped"):
        return "store_review_memory"
    return "fetch_pr_metadata"

def should_continue_after_meta(state: PRReviewState) -> Literal["fetch_changed_files", "store_review_memory"]:
    if state.get("status") in ("failed", "skipped"):
        return "store_review_memory"
    return "fetch_changed_files"

def should_continue_after_files(state: PRReviewState) -> Literal["retrieve_repository_context", "store_review_memory"]:
    if state.get("status") in ("failed", "skipped"):
        return "store_review_memory"
    return "retrieve_repository_context"

def should_continue_after_rag(state: PRReviewState) -> Literal["review_code", "store_review_memory"]:
    if state.get("status") in ("failed", "skipped"):
        return "store_review_memory"
    return "review_code"

def should_continue_after_review(state: PRReviewState) -> Literal["generate_findings", "store_review_memory"]:
    if state.get("status") in ("failed", "skipped"):
        return "store_review_memory"
    return "generate_findings"

def should_continue_after_findings(state: PRReviewState) -> Literal["generate_summary", "store_review_memory"]:
    if state.get("status") in ("failed", "skipped"):
        return "store_review_memory"
    return "generate_summary"

def should_continue_after_summary(state: PRReviewState) -> Literal["post_comments", "store_review_memory"]:
    if state.get("status") in ("failed", "skipped"):
        return "store_review_memory"
    return "post_comments"


# Construct LangGraph StateGraph
builder = StateGraph(PRReviewState)

builder.add_node("validate_event", validate_event_node)
builder.add_node("fetch_pr_metadata", fetch_pr_metadata_node)
builder.add_node("fetch_changed_files", fetch_changed_files_node)
builder.add_node("retrieve_repository_context", retrieve_repository_context_node)
builder.add_node("review_code", review_code_node)
builder.add_node("generate_findings", generate_findings_node)
builder.add_node("generate_summary", generate_summary_node)
builder.add_node("post_comments", post_comments_node)
builder.add_node("store_review_memory", store_review_memory_node)

# Connect edges
builder.set_entry_point("validate_event")

builder.add_conditional_edges("validate_event", should_continue)
builder.add_conditional_edges("fetch_pr_metadata", should_continue_after_meta)
builder.add_conditional_edges("fetch_changed_files", should_continue_after_files)
builder.add_conditional_edges("retrieve_repository_context", should_continue_after_rag)
builder.add_conditional_edges("review_code", should_continue_after_review)
builder.add_conditional_edges("generate_findings", should_continue_after_findings)
builder.add_conditional_edges("generate_summary", should_continue_after_summary)

builder.add_edge("post_comments", "store_review_memory")
builder.add_edge("store_review_memory", END)

# Compile graph
review_workflow = builder.compile()
