import asyncio
from pathlib import Path
from app.rag.indexer import RepositoryIndexer

async def main():
    indexer = RepositoryIndexer()
    repo_name = "rejoy2004-rgb/ai-code-reviewer"
    local_path = Path(r"C:\Users\rejoy\.gemini\antigravity\scratch\github-pr-reviewer")
    
    print(f"Indexing repository '{repo_name}' from {local_path}...")
    count = await indexer.index_repository(repo_name, local_path)
    print(f"Index complete! Successfully indexed {count} code chunks.")

if __name__ == "__main__":
    asyncio.run(main())
