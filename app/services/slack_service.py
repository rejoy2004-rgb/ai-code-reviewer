import logging
from typing import Dict, Any, List, Optional
import httpx
from app.config.settings import settings

logger = logging.getLogger("app.slack_service")


class SlackService:
    def __init__(self, webhook_url: Optional[str] = None):
        self.webhook_url = webhook_url or settings.SLACK_WEBHOOK_URL

    async def send_review_notification(
        self,
        repo_name: str,
        pr_number: int,
        pr_title: str,
        pr_url: str,
        pr_author: str,
        score: float,
        risk_score: float,
        confidence_score: float,
        findings_summary: str,
        categories_count: Dict[str, int]
    ) -> bool:
        """
        Sends a rich Slack block notification summarizing a pull request review.
        """
        if not self.webhook_url:
            logger.info("Slack webhook URL not configured. Skipping Slack notification.")
            return False

        # Format scores with color emojis
        score_emoji = "🟢" if score >= 8.0 else ("🟡" if score >= 6.0 else "🔴")
        risk_emoji = "🟢" if risk_score <= 3.0 else ("🟡" if risk_score <= 6.0 else "🔴")
        
        # Build category breakdown string
        category_breakdown = ", ".join([f"*{k}*: {v}" for k, v in categories_count.items() if v > 0])
        if not category_breakdown:
            category_breakdown = "_None (Code looks clean!)_"

        # Truncate summary if too long for Slack block limits (max 3000 characters per text block)
        truncated_summary = findings_summary
        if len(truncated_summary) > 1000:
            truncated_summary = truncated_summary[:997] + "..."

        # Setup Slack block layout
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": "🤖 AI Pull Request Review Complete",
                    "emoji": True
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Repository:* `{repo_name}`\n*PR:* <{pr_url}|#{pr_number} - {pr_title}>\n*Author:* @{pr_author}"
                }
            },
            {"type": "divider"},
            {
                "type": "section",
                "fields": [
                    {
                        "type": "mrkdwn",
                        "text": f"*Quality Score:*\n{score_emoji} `{score:.1f}/10`"
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Risk Level:*\n{risk_emoji} `{risk_score:.1f}/10`"
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Confidence:*\n🧠 `{confidence_score:.1f}/10`"
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*Issues Count:*\n🛠️ {sum(categories_count.values())} total"
                    }
                ]
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Breakdown by Category:*\n{category_breakdown}"
                }
            },
            {"type": "divider"},
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Executive Summary Highlights:*\n{truncated_summary}"
                }
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "View Pull Request",
                            "emoji": True
                        },
                        "url": pr_url,
                        "style": "primary"
                    }
                ]
            }
        ]

        payload = {"blocks": blocks}

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(self.webhook_url, json=payload, timeout=10.0)
                if response.status_code == 200:
                    logger.info("Successfully posted review notification to Slack.")
                    return True
                else:
                    logger.error(f"Failed to send Slack notification. Status: {response.status_code}, Body: {response.text}")
                    return False
            except Exception as e:
                logger.error(f"Error calling Slack webhook: {e}")
                return False
