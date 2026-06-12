# scratch_index.py
import asyncio
from pathlib import Path
from app.rag.indexer import RepositoryIndexer

async def run():
    indexer = RepositoryIndexer()
    # Example: Index this reviewer project itself!
    repo_path = Path("C:/Users/rejoy/.gemini/antigravity/scratch/github-pr-reviewer")
    repo_name = "rejoy/github-pr-reviewer"
    print(f"Indexing {repo_path}...")
    count = await indexer.index_repository(repo_name, repo_path)
    print(f"Indexing complete! Indexed {count} code chunks.")

if __name__ == "__main__":
    asyncio.run(run())