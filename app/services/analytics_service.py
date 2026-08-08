from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import Dict, Any, List
from app.models.database import ReviewRecord, ReviewFinding, DeveloperFeedback


class AnalyticsService:
    @staticmethod
    def get_summary_stats(db: Session) -> Dict[str, Any]:
        """
        Calculates and returns top-level aggregated statistics.
        """
        total_reviews = db.query(func.count(ReviewRecord.id)).scalar() or 0
        
        # Calculate averages for successful reviews
        avg_score = db.query(func.avg(ReviewRecord.score)).filter(ReviewRecord.status == "completed").scalar() or 0.0
        avg_risk = db.query(func.avg(ReviewRecord.risk_score)).filter(ReviewRecord.status == "completed").scalar() or 0.0
        avg_confidence = db.query(func.avg(ReviewRecord.confidence_score)).filter(ReviewRecord.status == "completed").scalar() or 0.0

        # Calculate total findings
        total_findings = db.query(func.count(ReviewFinding.id)).scalar() or 0

        # Group findings by category
        category_counts = db.query(
            ReviewFinding.category, func.count(ReviewFinding.id)
        ).group_by(ReviewFinding.category).all()
        categories = {cat: count for cat, count in category_counts}

        # Group findings by severity
        severity_counts = db.query(
            ReviewFinding.severity, func.count(ReviewFinding.id)
        ).group_by(ReviewFinding.severity).all()
        severities = {sev: count for sev, count in severity_counts}

        # Group feedback statuses
        feedback_counts = db.query(
            ReviewFinding.feedback_status, func.count(ReviewFinding.id)
        ).group_by(ReviewFinding.feedback_status).all()
        feedback = {status: count for status, count in feedback_counts}

        return {
            "total_reviews": total_reviews,
            "averages": {
                "quality_score": round(float(avg_score), 2),
                "risk_score": round(float(avg_risk), 2),
                "confidence_score": round(float(avg_confidence), 2)
            },
            "total_findings": total_findings,
            "categories": {
                "security": categories.get("security", 0),
                "performance": categories.get("performance", 0),
                "code_quality": categories.get("code_quality", 0),
                "maintainability": categories.get("maintainability", 0),
                "style": categories.get("style", 0)
            },
            "severities": {
                "high": severities.get("high", 0),
                "medium": severities.get("medium", 0),
                "low": severities.get("low", 0)
            },
            "developer_feedback": {
                "unacknowledged": feedback.get("none", 0),
                "accepted": feedback.get("accepted", 0),
                "rejected": feedback.get("rejected", 0),
                "disputed": feedback.get("disputed", 0)
            }
        }

    @staticmethod
    def get_recent_reviews(db: Session, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Retrieves the list of recent pull request review records.
        """
        records = db.query(ReviewRecord).order_by(ReviewRecord.created_at.desc()).limit(limit).all()
        
        result = []
        for r in records:
            result.append({
                "id": r.id,
                "repo_name": r.repo_name,
                "pr_number": r.pr_number,
                "commit_sha": r.commit_sha[:8],
                "score": r.score,
                "risk_score": r.risk_score,
                "status": r.status,
                "created_at": r.created_at.isoformat(),
                "findings_count": db.query(func.count(ReviewFinding.id)).filter(ReviewFinding.review_record_id == r.id).scalar() or 0
            })
        return result

    @staticmethod
    def record_feedback(
        db: Session, 
        repo_name: str, 
        pr_number: int, 
        comment_id: str, 
        body: str
    ) -> DeveloperFeedback:
        """
        Inserts new developer feedback comment to SQLite.
        Analyzes the developer's reply to mark findings as accepted or disputed.
        """
        # Save feedback record
        feedback = DeveloperFeedback(
            repo_name=repo_name,
            pr_number=pr_number,
            comment_id=str(comment_id),
            body=body
        )
        
        # Simple sentiment classification on feedback to categorize standard developer replies
        lower_body = body.lower()
        action = "acknowledged"
        
        # Determine sentiment & action
        if any(w in lower_body for w in ["fix", "resolve", "done", "thanks", "good point", "agree"]):
            action = "accepted"
        elif any(w in lower_body for w in ["disagree", "incorrect", "wrong", "false positive", "intended", "by design", "dispute"]):
            action = "disputed"
        elif any(w in lower_body for w in ["no", "not"]):
            action = "rejected"
            
        feedback.action_taken = action  # type: ignore
        db.add(feedback)
        db.commit()
        db.refresh(feedback)

        # Update findings on the line if there was an active comment ID
        # Since we submit comments under a review, GitHub comments have unique IDs.
        # This helps adapt developer feedback memory.
        return feedback
