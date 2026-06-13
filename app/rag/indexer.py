import os
import re
import logging
from pathlib import Path
from typing import List, Optional

import chromadb
from sentence_transformers import SentenceTransformer

from app.config.settings import settings
from app.utils.rate_limiter import async_retry

logger = logging.getLogger("app.indexer")

# Local embedding model (no API key required)
embedding_model = SentenceTransformer(
    "sentence-transformers/all-MiniLM-L6-v2"
)


def sanitize_collection_name(name: str) -> str:
    """
    Sanitizes repository name to meet ChromaDB collection name constraints:
    - 3-63 characters
    - Alphanumeric, underscores, or hyphens
    - Starts and ends with alphanumeric
    """
    sanitized = re.sub(r"[^a-zA-Z0-9_-]", "_", name)
    sanitized = re.sub(r"__+", "_", sanitized)
    sanitized = sanitized.strip("_").strip("-")

    if len(sanitized) < 3:
        sanitized = f"repo_{sanitized}"

    return sanitized[:63]


class CodeChunk:
    def __init__(
        self,
        file_path: str,
        content: str,
        start_line: int,
        end_line: int,
    ):
        self.file_path = file_path
        self.content = content
        self.start_line = start_line
        self.end_line = end_line


class RepositoryIndexer:
    def __init__(self, chroma_dir: Optional[str] = None):
        self.chroma_dir = chroma_dir or settings.CHROMADB_DIR

        self.chroma_client = chromadb.PersistentClient(
            path=self.chroma_dir
        )

    def get_collection(self, repo_name: str):
        """
        Creates or gets a ChromaDB collection.
        """
        collection_name = sanitize_collection_name(repo_name)

        return self.chroma_client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    def chunk_file(
        self,
        file_path: Path,
        relative_path: str,
        max_chunk_lines: int = 50,
        overlap_lines: int = 10,
    ) -> List[CodeChunk]:

        chunks: List[CodeChunk] = []

        try:
            content = file_path.read_text(
                encoding="utf-8",
                errors="ignore",
            )

        except Exception as e:
            logger.error(
                f"Error reading file {file_path}: {e}"
            )
            return chunks

        lines = content.splitlines()
        total_lines = len(lines)

        if total_lines == 0:
            return chunks

        if total_lines <= max_chunk_lines:
            chunks.append(
                CodeChunk(
                    relative_path,
                    content,
                    1,
                    total_lines,
                )
            )
            return chunks

        start = 0

        while start < total_lines:

            end = min(
                start + max_chunk_lines,
                total_lines,
            )

            chunk_lines = lines[start:end]

            chunks.append(
                CodeChunk(
                    relative_path,
                    "\n".join(chunk_lines),
                    start + 1,
                    end,
                )
            )

            start += (
                max_chunk_lines - overlap_lines
            )

            if start >= total_lines:
                break

        return chunks

    def scan_directory(
        self,
        repo_path: Path,
    ) -> List[CodeChunk]:

        all_chunks: List[CodeChunk] = []

        exclude_dirs = {
            ".git",
            ".github",
            "node_modules",
            "venv",
            ".venv",
            "env",
            "__pycache__",
            "build",
            "dist",
            "data",
            "tests",
            ".gemini",
            "brain",
        }

        exclude_extensions = {
            ".png",
            ".jpg",
            ".jpeg",
            ".gif",
            ".ico",
            ".pdf",
            ".zip",
            ".tar",
            ".gz",
            ".db",
            ".sqlite",
            ".pyc",
            ".exe",
            ".bin",
            ".woff",
            ".woff2",
            ".ttf",
        }

        for root, dirs, files in os.walk(repo_path):

            dirs[:] = [
                d for d in dirs
                if d not in exclude_dirs
            ]

            for file in files:

                file_path = Path(root) / file

                if file_path.suffix in exclude_extensions:
                    continue

                if file.startswith("."):
                    continue

                relative_path = os.path.relpath(
                    file_path,
                    repo_path,
                ).replace("\\", "/")

                chunks = self.chunk_file(
                    file_path,
                    relative_path,
                )

                all_chunks.extend(chunks)

        return all_chunks

    @async_retry(
        max_retries=5,
        initial_delay=3.0,
        retryable_exceptions=(Exception,),
    )
    async def _get_embedding(
        self,
        text: str,
    ) -> List[float]:
        """
        Generates embedding locally using
        SentenceTransformer.
        """

        embedding = embedding_model.encode(
            text,
            convert_to_tensor=False,
        )

        return embedding.tolist()

    async def index_repository(
        self,
        repo_name: str,
        local_path: Path,
    ) -> int:

        logger.info(
            f"Indexing repository "
            f"'{repo_name}' from {local_path}..."
        )

        chunks = self.scan_directory(local_path)

        if not chunks:
            logger.warning(
                "No indexable code chunks found."
            )
            return 0

        try:
            self.chroma_client.delete_collection(
                sanitize_collection_name(
                    repo_name
                )
            )
        except Exception:
            pass

        collection = self.get_collection(
            repo_name
        )

        batch_size = 50
        indexed_count = 0

        for i in range(
            0,
            len(chunks),
            batch_size,
        ):

            batch = chunks[
                i:i + batch_size
            ]

            ids = []
            documents = []
            embeddings = []
            metadatas = []

            for chunk in batch:

                try:
                    embedding = (
                        await self._get_embedding(
                            chunk.content
                        )
                    )

                    chunk_id = (
                        f"{chunk.file_path}_"
                        f"{chunk.start_line}_"
                        f"{chunk.end_line}"
                    )

                    ids.append(chunk_id)

                    documents.append(
                        chunk.content
                    )

                    embeddings.append(
                        embedding
                    )

                    metadatas.append(
                        {
                            "file_path": chunk.file_path,
                            "start_line": chunk.start_line,
                            "end_line": chunk.end_line,
                            "repo_name": repo_name,
                        }
                    )

                except Exception as e:

                    logger.error(
                        f"Failed embedding "
                        f"{chunk.file_path}: {e}"
                    )

            if ids:

                collection.add(
                    ids=ids,
                    embeddings=embeddings,
                    documents=documents,
                    metadatas=metadatas,
                )

                indexed_count += len(ids)

                logger.info(
                    f"Indexed "
                    f"{indexed_count}/"
                    f"{len(chunks)} chunks..."
                )

        logger.info(
            f"Indexing completed. "
            f"Total chunks indexed: "
            f"{indexed_count}"
        )

        return indexed_count
