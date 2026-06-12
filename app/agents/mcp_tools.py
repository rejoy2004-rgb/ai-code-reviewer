import logging
from typing import List, Dict, Any, Optional
from app.github.client import GitHubClient
from app.rag.retriever import RepositoryRetriever

logger = logging.getLogger("app.mcp_tools")

# Initialize clients
github_client = GitHubClient()
retriever = RepositoryRetriever()


# Define the MCP tool schemas & function implementations

async def get_pull_request(repo_owner: str, repo_name: str, pr_number: int) -> Dict[str, Any]:
    """
    Fetches the details and metadata of a pull request from GitHub.
    
    Args:
        repo_owner: The username or organization owner of the repository.
        repo_name: The name of the repository.
        pr_number: The pull request number.
    """
    logger.info(f"MCP Tool 'get_pull_request' called for {repo_owner}/{repo_name} #{pr_number}")
    return await github_client.get_pull_request(repo_owner, repo_name, pr_number)


async def get_changed_files(repo_owner: str, repo_name: str, pr_number: int) -> List[Dict[str, Any]]:
    """
    Fetches the list of changed files and their diff patches in a pull request.
    
    Args:
        repo_owner: The username or organization owner of the repository.
        repo_name: The name of the repository.
        pr_number: The pull request number.
    """
    logger.info(f"MCP Tool 'get_changed_files' called for {repo_owner}/{repo_name} #{pr_number}")
    return await github_client.get_changed_files(repo_owner, repo_name, pr_number)


async def search_repository(
    repo_owner: str,
    repo_name: str,
    query: str,
    file_filter: Optional[str] = None,
    limit: int = 3
) -> List[Dict[str, Any]]:
    """
    Performs a semantic vector search across the repository codebase for patterns or conventions.
    
    Args:
        repo_owner: The username or organization owner of the repository.
        repo_name: The name of the repository.
        query: The semantic text or code snippet to search for.
        file_filter: Optional file path to restrict results.
        limit: Maximum number of search results to return (default is 3).
    """
    repo_full_name = f"{repo_owner}/{repo_name}"
    logger.info(f"MCP Tool 'search_repository' called for '{repo_full_name}' with query: '{query}'")
    return await retriever.retrieve_similar_code(
        repo_name=repo_full_name,
        query_text=query,
        limit=limit,
        file_filter=file_filter
    )


async def create_review_comment(
    repo_owner: str,
    repo_name: str,
    pr_number: int,
    commit_id: str,
    file_path: str,
    line: int,
    comment_body: str,
    side: str = "RIGHT"
) -> Dict[str, Any]:
    """
    Creates a single inline review comment on a specific line of a file in the pull request.
    
    Args:
        repo_owner: The username or organization owner of the repository.
        repo_name: The name of the repository.
        pr_number: The pull request number.
        commit_id: The SHA of the commit being reviewed (head SHA).
        file_path: The relative path of the file being commented on.
        line: The line number in the file (1-indexed).
        comment_body: The review comments/recommendation text (Markdown format).
        side: The side of the diff to comment on, either 'LEFT' (old code) or 'RIGHT' (new code). Default is 'RIGHT'.
    """
    logger.info(f"MCP Tool 'create_review_comment' called for {repo_owner}/{repo_name} #{pr_number} on {file_path}:{line}")
    return await github_client.create_review_comment(
        repo_owner=repo_owner,
        repo_name=repo_name,
        pr_number=pr_number,
        commit_id=commit_id,
        file_path=file_path,
        line=line,
        body=comment_body,
        side=side
    )


async def create_summary_comment(
    repo_owner: str,
    repo_name: str,
    pr_number: int,
    summary_body: str
) -> Dict[str, Any]:
    """
    Creates a general comment on the pull request (a summary comment).
    
    Args:
        repo_owner: The username or organization owner of the repository.
        repo_name: The name of the repository.
        pr_number: The pull request number.
        summary_body: The overall summary markdown text.
    """
    logger.info(f"MCP Tool 'create_summary_comment' called for {repo_owner}/{repo_name} #{pr_number}")
    return await github_client.create_summary_comment(
        repo_owner=repo_owner,
        repo_name=repo_name,
        pr_number=pr_number,
        body=summary_body
    )


# Registry mapping tool names to their respective functions and schemas (useful for building MCP servers)
MCP_TOOLS_REGISTRY = {
    "get_pull_request": {
        "function": get_pull_request,
        "description": "Fetch pull request metadata from GitHub",
        "parameters": {
            "type": "object",
            "properties": {
                "repo_owner": {"type": "string", "description": "Repository owner"},
                "repo_name": {"type": "string", "description": "Repository name"},
                "pr_number": {"type": "integer", "description": "PR number"}
            },
            "required": ["repo_owner", "repo_name", "pr_number"]
        }
    },
    "get_changed_files": {
        "function": get_changed_files,
        "description": "Get changed files and diff patches in a PR",
        "parameters": {
            "type": "object",
            "properties": {
                "repo_owner": {"type": "string", "description": "Repository owner"},
                "repo_name": {"type": "string", "description": "Repository name"},
                "pr_number": {"type": "integer", "description": "PR number"}
            },
            "required": ["repo_owner", "repo_name", "pr_number"]
        }
    },
    "search_repository": {
        "function": search_repository,
        "description": "Semantic search in repository using ChromaDB vector index",
        "parameters": {
            "type": "object",
            "properties": {
                "repo_owner": {"type": "string", "description": "Repository owner"},
                "repo_name": {"type": "string", "description": "Repository name"},
                "query": {"type": "string", "description": "Search query"},
                "file_filter": {"type": "string", "description": "Optional file path filter"},
                "limit": {"type": "integer", "description": "Max results to return"}
            },
            "required": ["repo_owner", "repo_name", "query"]
        }
    },
    "create_review_comment": {
        "function": create_review_comment,
        "description": "Post a line-by-line review comment on a PR",
        "parameters": {
            "type": "object",
            "properties": {
                "repo_owner": {"type": "string", "description": "Repository owner"},
                "repo_name": {"type": "string", "description": "Repository name"},
                "pr_number": {"type": "integer", "description": "PR number"},
                "commit_id": {"type": "string", "description": "PR Head commit SHA"},
                "file_path": {"type": "string", "description": "Relative file path"},
                "line": {"type": "integer", "description": "Line number in the file"},
                "comment_body": {"type": "string", "description": "Comment content in Markdown"},
                "side": {"type": "string", "enum": ["LEFT", "RIGHT"], "description": "Side of diff"}
            },
            "required": ["repo_owner", "repo_name", "pr_number", "commit_id", "file_path", "line", "comment_body"]
        }
    },
    "create_summary_comment": {
        "function": create_summary_comment,
        "description": "Post a general PR summary comment",
        "parameters": {
            "type": "object",
            "properties": {
                "repo_owner": {"type": "string", "description": "Repository owner"},
                "repo_name": {"type": "string", "description": "Repository name"},
                "pr_number": {"type": "integer", "description": "PR number"},
                "summary_body": {"type": "string", "description": "Summary content in Markdown"}
            },
            "required": ["repo_owner", "repo_name", "pr_number", "summary_body"]
        }
    }
}
