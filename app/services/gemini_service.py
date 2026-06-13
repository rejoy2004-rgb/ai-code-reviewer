import json
import logging
import asyncio
import httpx
import re

from typing import List, Dict, Any, Optional

from app.config.settings import settings
from app.models.schemas import (
    LineFinding,
    FileReviewResponse,
    PRSummaryResponse,
)

from app.prompts.review_prompts import (
    CODE_REVIEW_SYSTEM_PROMPT,
    CODE_REVIEW_USER_TEMPLATE,
)

from app.prompts.summary_prompts import (
    SUMMARY_SYSTEM_PROMPT,
    SUMMARY_USER_TEMPLATE,
)

from app.utils.rate_limiter import (
    async_retry,
    gemini_rate_limiter,
)


def extract_json(text: str) -> str:
    """
    Extracts the outermost JSON object ({...}) or array ([...]) from LLM output text.
    """
    text = text.strip()
    # Remove markdown code block markers
    text = re.sub(r"^```json\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^```\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    text = text.strip()

    # Search for outermost array [ ... ] and object { ... }
    array_match = re.search(r"\[.*\]", text, re.DOTALL)
    object_match = re.search(r"\{.*\}", text, re.DOTALL)

    if array_match and object_match:
        # Return whichever matches first in the text
        if array_match.start() < object_match.start():
            return array_match.group(0)
        else:
            return object_match.group(0)
    elif array_match:
        return array_match.group(0)
    elif object_match:
        return object_match.group(0)

    return text


logger = logging.getLogger("app.gemini_service")


class GeminiService:
    """
    Uses OpenRouter instead of Gemini.
    Kept the class name unchanged so the rest
    of the project does not need refactoring.
    """

    def __init__(self, model_name: Optional[str] = None):
        self.model_name = model_name or settings.OPENROUTER_MODEL

    async def _call_openrouter(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
    ) -> str:
        api_key = settings.OPENROUTER_API_KEY
        if not api_key or not api_key.strip():
            raise ValueError(
                "OPENROUTER_API_KEY is not set or is empty. Please set it as a Repository Secret "
                "named 'OPENROUTER_API_KEY' in your GitHub repository settings under Settings -> "
                "Secrets and variables -> Actions."
            )
        headers = {
            "Authorization": f"Bearer {api_key.strip()}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.model_name,
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {
                    "role": "user",
                    "content": user_prompt,
                },
            ],
            "temperature": temperature,
            "response_format": {
                "type": "json_object"
            }
        }

        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"]

    @async_retry(
        max_retries=5,
        initial_delay=3.0,
        retryable_exceptions=(Exception,),
    )
    async def review_file_diff(
        self,
        file_path: str,
        diff_content: str,
        rag_context: str,
    ) -> List[LineFinding]:
        if not diff_content.strip():
            return []

        user_prompt = CODE_REVIEW_USER_TEMPLATE.format(
            file_path=file_path,
            rag_context=rag_context,
            diff_content=diff_content,
        )

        logger.info(f"Reviewing file: {file_path}")

        await gemini_rate_limiter.acquire()

        response_text = await self._call_openrouter(
            system_prompt=CODE_REVIEW_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.2,
        )

        logger.warning(
            f"\n===== RAW RESPONSE ({file_path}) =====\n"
            f"{response_text}\n"
            f"==============================="
        )

        try:
            cleaned = extract_json(response_text)
            if cleaned == "[]":
                return []

            logger.warning(f"RAW RESPONSE FOR {file_path}:\n{response_text}")
            logger.warning(f"CLEANED RESPONSE:\n{cleaned}")

            # Parse response text as standard JSON to allow normalization of field name variations
            parsed_data = json.loads(cleaned)
            findings_list = []

            # If response is a direct list (array of findings)
            if isinstance(parsed_data, list):
                findings_list = parsed_data
            # If response is an object, check for "findings" list key
            elif isinstance(parsed_data, dict):
                if "findings" in parsed_data and isinstance(parsed_data["findings"], list):
                    findings_list = parsed_data["findings"]
                elif "finding" in parsed_data or "issue" in parsed_data:
                    # Single finding returned as an object
                    findings_list = [parsed_data]

            # Normalize keys to align with LineFinding pydantic schema
            valid_categories = {"security", "performance", "code_quality", "maintainability", "style"}
            normalized_findings = []

            for item in findings_list:
                if not isinstance(item, dict):
                    continue

                # Map alias keys
                issue = item.get("issue") or item.get("finding") or "Code issue detected"
                line = item.get("line") or item.get("target_line")
                category = item.get("category", "code_quality").lower()
                severity = item.get("severity", "medium").lower()
                recommendation = item.get("recommendation") or item.get("suggested_fix") or "Please review and refactor."

                if category not in valid_categories:
                    category = "code_quality"
                if severity not in {"low", "medium", "high"}:
                    severity = "medium"

                # Parse line to int safely
                try:
                    line = int(line) if line is not None else None
                except ValueError:
                    line = None

                normalized_findings.append({
                    "severity": severity,
                    "category": category,
                    "file": item.get("file") or file_path,
                    "line": line,
                    "issue": issue,
                    "recommendation": recommendation
                })

            # Reconstruct and validate via Pydantic model
            parsed = FileReviewResponse(
                findings=[LineFinding(**f) for f in normalized_findings]
            )

            logger.info(
                f"Reviewed {file_path}. "
                f"Found {len(parsed.findings)} findings."
            )
            return parsed.findings

        except Exception as e:
            logger.error(f"JSON parsing failed for {file_path}: {e}")
            return []

    @async_retry(
        max_retries=5,
        initial_delay=3.0,
        retryable_exceptions=(Exception,),
    )
    async def generate_pr_summary(
        self,
        pr_metadata: Dict[str, Any],
        findings: List[LineFinding],
    ) -> PRSummaryResponse:
        title = pr_metadata.get("title", "Untitled PR")
        description = pr_metadata.get("body", "No description provided.")
        author = pr_metadata.get("user", {}).get("login", "Unknown")
        head_branch = pr_metadata.get("head", {}).get("ref", "unknown")
        base_branch = pr_metadata.get("base", {}).get("ref", "unknown")

        findings_text = ""
        if not findings:
            findings_text = "No specific issues identified."
        else:
            for idx, f in enumerate(findings):
                findings_text += (
                    f"{idx+1}. "
                    f"File: {f.file}\n"
                    f"Line: {f.line}\n"
                    f"Category: {f.category}\n"
                    f"Severity: {f.severity}\n"
                    f"Issue: {f.issue}\n"
                    f"Recommendation: {f.recommendation}\n\n"
                )

        user_prompt = SUMMARY_USER_TEMPLATE.format(
            title=title,
            description=description,
            author=author,
            head_branch=head_branch,
            base_branch=base_branch,
            findings_text=findings_text,
        )

        logger.info(f"Generating PR summary for PR #{pr_metadata.get('number')}")

        await gemini_rate_limiter.acquire()

        response_text = await self._call_openrouter(
            system_prompt=SUMMARY_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.3,
        )

        try:
            cleaned = extract_json(response_text)
            parsed = PRSummaryResponse.model_validate_json(cleaned)
            logger.info("Successfully generated PR summary.")
            return parsed
        except Exception as e:
            logger.error(f"Summary parse failed: {e}")
            try:
                cleaned = extract_json(response_text)
                data = json.loads(cleaned)
                return PRSummaryResponse(
                    score=float(data.get("score", 7.0)),
                    risk_score=float(data.get("risk_score", 5.0)),
                    confidence_score=float(data.get("confidence_score", 8.0)),
                    summary=data.get("summary", "Summary generation failed."),
                )
            except Exception:
                return PRSummaryResponse(
                    score=7.0,
                    risk_score=5.0,
                    confidence_score=5.0,
                    summary="Failed to generate summary.",
                )