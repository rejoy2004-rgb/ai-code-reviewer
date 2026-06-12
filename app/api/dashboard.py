import os
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Dict, Any, List

from app.db.session import get_db
from app.services.analytics_service import AnalyticsService
from app.rag.indexer import RepositoryIndexer

router = APIRouter()
indexer = RepositoryIndexer()


class IndexRequest(BaseModel):
    repo_name: str
    local_path: str


async def run_indexing_task(repo_name: str, local_path: Path):
    """Background task to run vector indexing."""
    try:
        await indexer.index_repository(repo_name, local_path)
    except Exception as e:
        import logging
        logging.getLogger("app.dashboard").error(f"Background indexing task failed: {e}")


@router.get("/summary")
def get_analytics_summary(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    Returns aggregated quality scores, risks, and findings count.
    """
    try:
        return AnalyticsService.get_summary_stats(db)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch stats: {str(e)}")


@router.get("/history")
def get_analytics_history(limit: int = 10, db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    """
    Returns lists of recent PR reviews.
    """
    try:
        return AnalyticsService.get_recent_reviews(db, limit=limit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch review history: {str(e)}")


@router.post("/index")
async def trigger_repo_indexing(
    payload: IndexRequest,
    background_tasks: BackgroundTasks
):
    """
    Triggers indexing of a local directory into ChromaDB vector store.
    """
    path = Path(payload.local_path)
    if not path.exists() or not path.is_dir():
        raise HTTPException(
            status_code=400, 
            detail=f"Local path '{payload.local_path}' does not exist or is not a directory."
        )

    # Schedule indexing in background
    background_tasks.add_task(run_indexing_task, payload.repo_name, path)
    
    return {
        "message": f"Vector indexing scheduled in the background for repository '{payload.repo_name}'",
        "path": str(path.absolute())
    }
