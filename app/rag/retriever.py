import logging
from typing import List, Dict, Any, Optional

import chromadb
from sentence_transformers import SentenceTransformer

from app.config.settings import settings
from app.rag.indexer import sanitize_collection_name
from app.utils.rate_limiter import async_retry

logger = logging.getLogger("app.retriever")

# Same embedding model used in indexer.py
embedding_model = SentenceTransformer(
    "sentence-transformers/all-MiniLM-L6-v2"
)


class RepositoryRetriever:
    def __init__(self, chroma_dir: Optional[str] = None):
        self.chroma_dir = chroma_dir or settings.CHROMADB_DIR

        self.chroma_client = chromadb.PersistentClient(
            path=self.chroma_dir
        )

    @async_retry(
        max_retries=5,
        initial_delay=3.0,
        retryable_exceptions=(Exception,)
    )
    async def _get_query_embedding(
        self,
        query_text: str
    ) -> List[float]:
        """
        Generate query embedding locally.
        """

        embedding = embedding_model.encode(
            query_text,
            convert_to_tensor=False
        )

        return embedding.tolist()

    async def retrieve_similar_code(
        self,
        repo_name: str,
        query_text: str,
        limit: int = 3,
        file_filter: Optional[str] = None
    ) -> List[Dict[str, Any]]:

        try:
            collection_name = sanitize_collection_name(
                repo_name
            )

            collection = self.chroma_client.get_collection(
                name=collection_name
            )

        except Exception as e:
            logger.warning(
                f"Could not get ChromaDB collection "
                f"'{repo_name}'. Error: {e}"
            )
            return []

        try:
            query_embedding = await self._get_query_embedding(
                query_text
            )

            where_clause = {}

            if file_filter:
                where_clause["file_path"] = file_filter

            results = collection.query(
                query_embeddings=[query_embedding],
                n_results=limit,
                where=where_clause if where_clause else None,
            )

            retrieved = []

            if (
                results
                and results.get("documents")
                and len(results["documents"]) > 0
            ):

                documents = results["documents"][0]
                metadatas = results["metadatas"][0]

                distances = (
                    results["distances"][0]
                    if "distances" in results
                    else [0.0] * len(documents)
                )

                for i in range(len(documents)):
                    retrieved.append(
                        {
                            "content": documents[i],
                            "file_path": metadatas[i].get(
                                "file_path"
                            ),
                            "start_line": metadatas[i].get(
                                "start_line"
                            ),
                            "end_line": metadatas[i].get(
                                "end_line"
                            ),
                            "distance": distances[i],
                        }
                    )

            return retrieved

        except Exception as e:
            logger.error(
                f"Error querying ChromaDB "
                f"for repo '{repo_name}': {e}"
            )
            return []

    async def retrieve_context_for_diff(
        self,
        repo_name: str,
        file_path: str,
        diff_content: str
    ) -> str:
        """
        Retrieves similar code chunks to provide
        project-specific context.
        """

        clean_query = "\n".join(
            [
                line[1:].strip()
                for line in diff_content.splitlines()
                if (
                    line.startswith("+")
                    or line.startswith("-")
                )
                and len(line.strip()) > 5
            ][:10]
        )

        if not clean_query.strip():
            return (
                "No matching patterns found "
                "(empty diff query)."
            )

        similar_chunks = (
            await self.retrieve_similar_code(
                repo_name,
                clean_query,
                limit=3,
            )
        )

        context_blocks = []

        for idx, chunk in enumerate(similar_chunks):

            if chunk["distance"] > 0.8:
                continue

            context_blocks.append(
                f"### Reference Code Example "
                f"{idx + 1} "
                f"(from file: "
                f"`{chunk['file_path']}`, "
                f"lines "
                f"{chunk['start_line']}-"
                f"{chunk['end_line']})\n"
                f"```python\n"
                f"{chunk['content']}\n"
                f"```\n"
            )

        if not context_blocks:
            return (
                "No comparable codebase "
                "conventions retrieved."
            )

        return "\n".join(context_blocks)