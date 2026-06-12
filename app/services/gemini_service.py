import json
import logging
from typing import List, Dict, Any, Optional
import google.generativeai as genai
from app.config.settings import settings
from app.models.schemas import LineFinding, FileReviewResponse, PRSummaryResponse
from app.prompts.review_prompts import CODE_REVIEW_SYSTEM_PROMPT, CODE_REVIEW_USER_TEMPLATE
from app.prompts.summary_prompts import SUMMARY_SYSTEM_PROMPT, SUMMARY_USER_TEMPLATE
from app.utils.rate_limiter import async_retry, gemini_rate_limiter

logger = logging.getLogger("app.gemini_service")

# Configure the SDK
genai.configure(api_key=settings.GEMINI_API_KEY)


class GeminiService:
    def __init__(self, model_name: Optional[str] = None):
        self.model_name = model_name or settings.GEMINI_MODEL

    @async_retry(max_retries=5, initial_delay=3.0, retryable_exceptions=(Exception,))
    async def review_file_diff(
        self,
        file_path: str,
        diff_content: str,
        rag_context: str
    ) -> List[LineFinding]:
        """
        Reviews a single file diff using Gemini Flash.
        Returns a list of LineFinding objects.
        """
        # Skip if diff is empty or trivial
        if not diff_content.strip():
            return []

        user_prompt = CODE_REVIEW_USER_TEMPLATE.format(
            file_path=file_path,
            rag_context=rag_context,
            diff_content=diff_content
        )

        logger.info(f"Calling Gemini to review file: {file_path}")
        
        # Acquire rate limiter slot
        await gemini_rate_limiter.acquire()
        
        # We run the synchronous SDK call in an executor to prevent blocking the async loop
        import asyncio
        loop = asyncio.get_event_loop()
        
        def call_gemini():
            model = genai.GenerativeModel(
                model_name=self.model_name,
                system_instruction=CODE_REVIEW_SYSTEM_PROMPT
            )
            config = genai.GenerationConfig(
                response_mime_type="application/json",
                response_schema=FileReviewResponse,
                temperature=0.2
            )
            return model.generate_content(user_prompt, generation_config=config)

        response = await loop.run_in_executor(None, call_gemini)
        
        try:
            parsed = FileReviewResponse.model_validate_json(response.text)
            logger.info(f"Successfully reviewed {file_path}. Found {len(parsed.findings)} issues.")
            return parsed.findings
        except Exception as e:
            logger.error(f"Error parsing Gemini JSON response for {file_path}: {e}. Raw response: {response.text}")
            # Try to recover if there was a minor syntax issue, or return empty findings
            try:
                data = json.loads(response.text)
                findings_data = data.get("findings", [])
                recovered_findings = [LineFinding(**f) for f in findings_data]
                return recovered_findings
            except Exception:
                return []

    @async_retry(max_retries=5, initial_delay=3.0, retryable_exceptions=(Exception,))
    async def generate_pr_summary(
        self,
        pr_metadata: Dict[str, Any],
        findings: List[LineFinding]
    ) -> PRSummaryResponse:
        """
        Aggregates all findings and generates the final PR review summary, scoring, and risk level.
        """
        title = pr_metadata.get("title", "Untitled PR")
        description = pr_metadata.get("body", "No description provided.")
        author = pr_metadata.get("user", {}).get("login", "Unknown")
        head_branch = pr_metadata.get("head", {}).get("ref", "unknown-branch")
        base_branch = pr_metadata.get("base", {}).get("ref", "unknown-branch")

        # Format findings list
        findings_text = ""
        if not findings:
            findings_text = "No specific issues identified. The changes look clean and well-structured."
        else:
            for idx, f in enumerate(findings):
                findings_text += (
                    f"{idx+1}. **File**: `{f.file}` | **Line**: {f.line or 'N/A'} | "
                    f"**Category**: `{f.category}` | **Severity**: `{f.severity}`\n"
                    f"   - **Issue**: {f.issue}\n"
                    f"   - **Recommendation**: {f.recommendation}\n"
                )

        user_prompt = SUMMARY_USER_TEMPLATE.format(
            title=title,
            description=description,
            author=author,
            head_branch=head_branch,
            base_branch=base_branch,
            findings_text=findings_text
        )

        logger.info(f"Calling Gemini to generate PR Review Summary for PR #{pr_metadata.get('number')}")
        
        await gemini_rate_limiter.acquire()
        
        import asyncio
        loop = asyncio.get_event_loop()
        
        def call_gemini():
            model = genai.GenerativeModel(
                model_name=self.model_name,
                system_instruction=SUMMARY_SYSTEM_PROMPT
            )
            config = genai.GenerationConfig(
                response_mime_type="application/json",
                response_schema=PRSummaryResponse,
                temperature=0.3
            )
            return model.generate_content(user_prompt, generation_config=config)

        response = await loop.run_in_executor(None, call_gemini)
        
        try:
            parsed = PRSummaryResponse.model_validate_json(response.text)
            logger.info("Successfully generated PR Review Summary and scores.")
            return parsed
        except Exception as e:
            logger.error(f"Error parsing Gemini summary JSON: {e}. Raw response: {response.text}")
            # Fallback parsing in case of structural errors
            try:
                data = json.loads(response.text)
                return PRSummaryResponse(
                    score=float(data.get("score", 7.0)),
                    risk_score=float(data.get("risk_score", 5.0)),
                    confidence_score=float(data.get("confidence_score", 8.0)),
                    summary=data.get("summary", "Error generating detailed summary.")
                )
            except Exception:
                # Absolute fallback
                return PRSummaryResponse(
                    score=7.0,
                    risk_score=5.0,
                    confidence_score=5.0,
                    summary=f"### PR Review Summary\n\n- **Score**: 7.0/10\n- **Risk**: Moderate\n\nWe encountered an error parsing the structured AI summary. However, {len(findings)} files were reviewed and individual comments have been posted."
                )
