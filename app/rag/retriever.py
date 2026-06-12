import logging
from typing import List, Dict, Any, Optional
import google.generativeai as genai
import chromadb
from app.config.settings import settings
from app.rag.indexer import sanitize_collection_name
from app.utils.rate_limiter import async_retry, gemini_rate_limiter

logger = logging.getLogger("app.retriever")

genai.configure(api_key=settings.GEMINI_API_KEY)


class RepositoryRetriever:
    def __init__(self, chroma_dir: Optional[str] = None):
        self.chroma_dir = chroma_dir or settings.CHROMADB_DIR
        self.chroma_client = chromadb.PersistentClient(path=self.chroma_dir)

    @async_retry(max_retries=5, initial_delay=3.0, retryable_exceptions=(Exception,))
    async def _get_query_embedding(self, query_text: str) -> List[float]:
        """Generates embedding for query text using Gemini Embeddings API."""
        await gemini_rate_limiter.acquire()
        response = genai.embed_content(
            model=settings.EMBEDDING_MODEL,
            content=query_text,
            task_type="retrieval_query"
        )
        return response["embedding"]

    async def retrieve_similar_code(
        self, 
        repo_name: str, 
        query_text: str, 
        limit: int = 3, 
        file_filter: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Retrieves similar code chunks from the repository collection.
        Optionally filters by file path or extension.
        """
        try:
            collection_name = sanitize_collection_name(repo_name)
            collection = self.chroma_client.get_collection(name=collection_name)
        except Exception as e:
            logger.warning(f"Could not get ChromaDB collection '{repo_name}'. It might not be indexed yet. Error: {e}")
            return []

        try:
            # Generate query embedding
            query_embedding = await self._get_query_embedding(query_text)
            
            # Prepare metadata filters
            where_clause = {}
            if file_filter:
                where_clause["file_path"] = file_filter

            # Perform similarity search
            results = collection.query(
                query_embeddings=[query_embedding],
                n_results=limit,
                where=where_clause if where_clause else None
            )

            retrieved = []
            if results and results.get("documents") and len(results["documents"]) > 0:
                documents = results["documents"][0]
                metadatas = results["metadatas"][0]
                distances = results["distances"][0] if "distances" in results else [0.0] * len(documents)
                
                for i in range(len(documents)):
                    retrieved.append({
                        "content": documents[i],
                        "file_path": metadatas[i].get("file_path"),
                        "start_line": metadatas[i].get("start_line"),
                        "end_line": metadatas[i].get("end_line"),
                        "distance": distances[i]
                    })
            
            return retrieved
        except Exception as e:
            logger.error(f"Error querying ChromaDB for repo '{repo_name}': {e}")
            return []

    async def retrieve_context_for_diff(self, repo_name: str, file_path: str, diff_content: str) -> str:
        """
        Queries the repository for context relevant to a specific file diff.
        Returns a formatted Markdown text explaining code conventions found in similar files.
        """
        # Search for code patterns that match the diff
        # Keep query concise to stay within limits
        # Only query if diff is substantial
        clean_query = "\n".join([
            line[1:].strip() 
            for line in diff_content.splitlines() 
            if (line.startswith("+") or line.startswith("-")) and len(line.strip()) > 5
        ][:10])  # Take first 10 added/modified lines

        if not clean_query.strip():
            return "No matching patterns found (empty diff query)."

        similar_chunks = await self.retrieve_similar_code(repo_name, clean_query, limit=3)
        
        # Filter out self-matches (exact matches to the same file that is being edited if we want)
        # However, looking at other files in the project is usually more helpful to see project-wide conventions.
        context_blocks = []
        for idx, chunk in enumerate(similar_chunks):
            # Skip if the similarity is very low (distance in cosine space close to 1.0)
            if chunk["distance"] > 0.8:
                continue
            
            # Avoid showing the exact same file if there are other files
            context_blocks.append(
                f"### Reference Code Example {idx + 1} (from file: `{chunk['file_path']}`, lines {chunk['start_line']}-{chunk['end_line']})\n"
                f"```python\n"
                f"{chunk['content']}\n"
                f"```\n"
            )

        if not context_blocks:
            return "No comparable codebase conventions retrieved."
            
        return "\n".join(context_blocks)
