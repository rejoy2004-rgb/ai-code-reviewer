from pydantic import BaseModel, Field
from typing import List, Literal, Optional


class LineFinding(BaseModel):
    severity: Literal["low", "medium", "high"] = Field(
        ..., description="The severity of the issue: high, medium, or low."
    )
    category: Literal["security", "performance", "code_quality", "maintainability", "style"] = Field(
        ..., description="The category of the issue."
    )
    file: str = Field(..., description="The path of the file containing the issue.")
    line: Optional[int] = Field(
        None, description="The 1-indexed line number in the target file where the issue occurs."
    )
    issue: str = Field(..., description="A clear description of the identified issue.")
    recommendation: str = Field(..., description="An actionable recommendation to resolve the issue.")


class FileReviewResponse(BaseModel):
    findings: List[LineFinding] = Field(
        default_factory=list, description="A list of code review findings for the analyzed code."
    )


class PRSummaryResponse(BaseModel):
    score: float = Field(
        ..., ge=1.0, le=10.0, description="Overall code quality score from 1.0 (poor) to 10.0 (pristine)."
    )
    risk_score: float = Field(
        ..., ge=1.0, le=10.0, description="Pull Request risk score from 1.0 (very low risk) to 10.0 (extremely high risk)."
    )
    confidence_score: float = Field(
        ..., ge=1.0, le=10.0, description="Review confidence score from 1.0 (low confidence) to 10.0 (high confidence)."
    )
    summary: str = Field(
        ..., description="High-level markdown summary of the PR review, outlining key strengths, main concerns, and a checklist of changes."
    )


# GitHub Webhook Schemas
class GitHubUser(BaseModel):
    login: str


class GitHubRepository(BaseModel):
    name: str
    full_name: str
    owner: GitHubUser


class GitHubPullRequestDetail(BaseModel):
    number: int
    state: str
    title: str
    body: Optional[str] = ""
    user: GitHubUser
    head: dict  # contains ref, sha, repo
    base: dict  # contains ref, sha, repo


class GitHubWebhookPayload(BaseModel):
    action: str
    number: Optional[int] = None
    pull_request: Optional[GitHubPullRequestDetail] = None
    repository: Optional[GitHubRepository] = None
    sender: Optional[GitHubUser] = None
