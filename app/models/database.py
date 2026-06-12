import datetime
from sqlalchemy import Column, Integer, Float, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from app.db.session import Base, engine


class ReviewRecord(Base):
    __tablename__ = "review_records"

    id = Column(Integer, primary_key=True, index=True)
    repo_name = Column(String, index=True, nullable=False)
    pr_number = Column(Integer, index=True, nullable=False)
    commit_sha = Column(String, index=True, nullable=False)
    score = Column(Float, nullable=True)
    risk_score = Column(Float, nullable=True)
    confidence_score = Column(Float, nullable=True)
    summary = Column(Text, nullable=True)
    status = Column(String, default="pending", nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    findings = relationship("ReviewFinding", back_populates="record", cascade="all, delete-orphan")


class ReviewFinding(Base):
    __tablename__ = "review_findings"

    id = Column(Integer, primary_key=True, index=True)
    review_record_id = Column(Integer, ForeignKey("review_records.id", ondelete="CASCADE"), nullable=False)
    file_path = Column(String, index=True, nullable=False)
    line_number = Column(Integer, nullable=True)
    category = Column(String, index=True, nullable=False)  # security, performance, code_quality, maintainability
    severity = Column(String, index=True, nullable=False)  # low, medium, high
    issue_description = Column(Text, nullable=False)
    recommendation = Column(Text, nullable=False)
    feedback_status = Column(String, default="none")  # none, accepted, rejected, disputed
    developer_notes = Column(Text, nullable=True)

    record = relationship("ReviewRecord", back_populates="findings")


class DeveloperFeedback(Base):
    __tablename__ = "developer_feedback"

    id = Column(Integer, primary_key=True, index=True)
    repo_name = Column(String, index=True, nullable=False)
    pr_number = Column(Integer, index=True, nullable=False)
    comment_id = Column(String, unique=True, index=True, nullable=False)
    body = Column(Text, nullable=False)
    action_taken = Column(String, nullable=True)  # e.g., acknowledged, disputed, code_updated
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)


def init_db():
    """Create all tables in the database."""
    Base.metadata.create_all(bind=engine)
