from typing import Dict, Any, List, TypedDict, Optional
from app.models.schemas import LineFinding


class PRReviewState(TypedDict):
    # Initial Webhook Inputs
    webhook_payload: Dict[str, Any]
    
    # Metadata extracted
    repo_full_name: str
    pr_number: int
    commit_sha: str
    pr_title: str
    pr_description: str
    pr_author: str
    pr_html_url: str
    
    # Code Files and Diffs
    changed_files: List[Dict[str, Any]]
    diff_map: Dict[str, Any]  # Maps file_path -> ParsedDiff
    
    # RAG Contexts retrieved from vector store
    rag_contexts: Dict[str, str]  # Maps file_path -> retrieved context snippet
    
    # AI Outputs
    raw_findings: List[LineFinding]
    filtered_findings: List[LineFinding]
    
    # PR Level Analysis
    score: float
    risk_score: float
    confidence_score: float
    summary_markdown: str
    
    # Execution Tracking
    db_record_id: Optional[int]
    status: str
    errors: List[str]
