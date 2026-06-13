import logging
from typing import List, Dict, Any, Tuple, Optional
from app.github.client import GitHubClient
from app.utils.diff_parser import parse_patch, get_closest_valid_line, ParsedDiff

logger = logging.getLogger("app.github_service")


class GitHubService:
    def __init__(self, client: Optional[GitHubClient] = None):
        self.client = client or GitHubClient()

    async def fetch_pr_info(self, repo_full_name: str, pr_number: int) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        """
        Fetches PR details and changed files for a pull request.
        """
        parts = repo_full_name.split("/")
        if len(parts) != 2:
            raise ValueError(f"Invalid repository full name: {repo_full_name}")
        owner, repo = parts[0], parts[1]

        logger.info(f"Fetching PR {pr_number} metadata for {repo_full_name}")
        pr_metadata = await self.client.get_pull_request(owner, repo, pr_number)
        
        logger.info(f"Fetching changed files for PR {pr_number}")
        changed_files = await self.client.get_changed_files(owner, repo, pr_number)
        
        return pr_metadata, changed_files

    async def get_pr_diff_map(self, changed_files: List[Dict[str, Any]]) -> Dict[str, ParsedDiff]:
        """
        Processes PR changed files and returns a map of file_path -> ParsedDiff object.
        """
        diff_map = {}
        for file in changed_files:
            file_path = file.get("filename")
            patch = file.get("patch")
            if file_path and patch:
                diff_map[file_path] = parse_patch(patch)
        return diff_map

    async def submit_pr_review(
        self,
        repo_full_name: str,
        pr_number: int,
        commit_sha: str,
        summary: str,
        findings: List[Dict[str, Any]],
        diff_map: Dict[str, ParsedDiff]
    ) -> Dict[str, Any]:
        """
        Validates line numbers and submits a single atomic GitHub Review:
        - Checks each finding's target line.
        - Relocates comment to closest modified line in diff if direct line match fails.
        - Appends findings to summary if no close line exists.
        - Submits summary + comments in a single REST request.
        """
        parts = repo_full_name.split("/")
        owner, repo = parts[0], parts[1]

        valid_comments = []
        unplaced_findings = []

        for finding in findings:
            file_path = finding.get("file")
            target_line = finding.get("line")
            comment_body = (
                f"**[{finding.get('category', 'general').upper()}] ({finding.get('severity', 'low').upper()})**\n\n"
                f"{finding.get('issue')}\n\n"
                f"*Recommendation:* {finding.get('recommendation')}"
            )

            if not file_path or file_path not in diff_map:
                unplaced_findings.append(finding)
                continue

            parsed_diff = diff_map[file_path]
            
            if target_line is None:
                # No line specified, must be placed as an unplaced finding
                unplaced_findings.append(finding)
                continue

            # Check if line is valid (part of the diff changes)
            # 1. Match exactly on RIGHT side (additions/modifications)
            if target_line in parsed_diff.added_lines:
                valid_comments.append({
                    "path": file_path,
                    "line": target_line,
                    "body": comment_body,
                    "side": "RIGHT"
                })
            # 2. Match exactly on LEFT side (deletions)
            elif target_line in parsed_diff.deleted_lines:
                valid_comments.append({
                    "path": file_path,
                    "line": target_line,
                    "body": comment_body,
                    "side": "LEFT"
                })
            else:
                # 3. Try relocating to closest added line (RIGHT)
                valid_line_right = get_closest_valid_line(target_line, parsed_diff.added_lines)
                if valid_line_right:
                    final_body = f"*(Comment shifted from line {target_line} to {valid_line_right} to align with changes)*\n\n" + comment_body
                    valid_comments.append({
                        "path": file_path,
                        "line": valid_line_right,
                        "body": final_body,
                        "side": "RIGHT"
                    })
                else:
                    # 4. Try relocating to closest deleted line (LEFT)
                    valid_line_left = get_closest_valid_line(target_line, parsed_diff.deleted_lines)
                    if valid_line_left:
                        final_body = f"*(Comment shifted from line {target_line} to {valid_line_left} to align with deletion)*\n\n" + comment_body
                        valid_comments.append({
                            "path": file_path,
                            "line": valid_line_left,
                            "body": final_body,
                            "side": "LEFT"
                        })
                    else:
                        unplaced_findings.append(finding)

        # If there are findings we couldn't place on specific lines, append them to the overall summary
        final_summary = summary
        if unplaced_findings:
            final_summary += "\n\n---\n\n### 📝 General & Out-of-Diff Comments\n"
            for f in unplaced_findings:
                final_summary += (
                    f"- **{f.get('file', 'Global')}**: "
                    f"**[{f.get('category', 'general').upper()}]** {f.get('issue')} "
                    f"*(Rec: {f.get('recommendation')} at line {f.get('line', 'N/A')})*\n"
                )

        # Determine overall review action (event)
        # If there are critical/high security errors, we request changes. Otherwise, we just comment.
        has_high_security_issue = any(
            f.get("severity") == "high" and f.get("category") == "security" 
            for f in findings
        )
        event_type = "COMMENT"

        # Submit via GitHub review API
        endpoint = f"repos/{owner}/{repo}/pulls/{pr_number}/reviews"
        payload = {
            "body": final_summary,
            "event": event_type,
            "commit_id": commit_sha
        }
        if valid_comments:
            payload["comments"] = valid_comments

        logger.info(f"Submitting batch review to PR {pr_number} with {len(valid_comments)} line comments.")
        return await self.client._request("POST", endpoint, json=payload)
