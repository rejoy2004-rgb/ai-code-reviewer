import os
import re
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
import chromadb
import google.generativeai as genai
from app.config.settings import settings
from app.utils.rate_limiter import async_retry, gemini_rate_limiter

logger = logging.getLogger("app.indexer")

# Configure Google Generative AI
genai.configure(api_key=settings.GEMINI_API_KEY)


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
    def __init__(self, file_path: str, content: str, start_line: int, end_line: int):
        self.file_path = file_path
        self.content = content
        self.start_line = start_line
        self.end_line = end_line


class RepositoryIndexer:
    def __init__(self, chroma_dir: Optional[str] = None):
        self.chroma_dir = chroma_dir or settings.CHROMADB_DIR
        self.chroma_client = chromadb.PersistentClient(path=self.chroma_dir)

    def get_collection(self, repo_name: str):
        """Creates or gets a ChromaDB collection for the repository."""
        collection_name = sanitize_collection_name(repo_name)
        return self.chroma_client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"}
        )

    def chunk_file(self, file_path: Path, relative_path: str, max_chunk_lines: int = 50, overlap_lines: int = 10) -> List[CodeChunk]:
        """
        Chunks a code file into smaller segments with overlapping lines.
        """
        chunks: List[CodeChunk] = []
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
        except Exception as e:
            logger.error(f"Error reading file {file_path}: {e}")
            return chunks

        lines = content.splitlines()
        total_lines = len(lines)

        if total_lines == 0:
            return chunks

        # If file is short, keep it as one chunk
        if total_lines <= max_chunk_lines:
            chunks.append(CodeChunk(relative_path, content, 1, total_lines))
            return chunks

        start = 0
        while start < total_lines:
            end = min(start + max_chunk_lines, total_lines)
            chunk_lines = lines[start:end]
            chunk_content = "\n".join(chunk_lines)
            
            chunks.append(CodeChunk(relative_path, chunk_content, start + 1, end))
            
            # Slide window forward
            start += max_chunk_lines - overlap_lines
            if start >= total_lines or end == total_lines:
                break

        return chunks

    def scan_directory(self, repo_path: Path) -> List[CodeChunk]:
        """Scans a local repository directory and returns list of chunks."""
        all_chunks: List[CodeChunk] = []
        exclude_dirs = {
            ".git", ".github", "node_modules", "venv", ".venv", "env", 
            "__pycache__", "build", "dist", "data", "tests", ".gemini", "brain"
        }
        exclude_extensions = {
            ".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".tar", 
            ".gz", ".db", ".sqlite", ".pyc", ".exe", ".bin", ".woff", ".woff2", ".ttf"
        }

        for root, dirs, files in os.walk(repo_path):
            # Prune directory search
            dirs[:] = [d for d in dirs if d not in exclude_dirs]
            
            for file in files:
                file_path = Path(root) / file
                if file_path.suffix in exclude_extensions:
                    continue
                
                # Exclude hidden files
                if file.startswith("."):
                    continue

                relative_path = os.path.relpath(file_path, repo_path).replace("\\", "/")
                chunks = self.chunk_file(file_path, relative_path)
                all_chunks.extend(chunks)

        return all_chunks

    @async_retry(max_retries=5, initial_delay=3.0, retryable_exceptions=(Exception,))
    async def _get_embedding(self, text: str) -> List[float]:
        """Generates embedding for a chunk of text using Gemini API."""
        await gemini_rate_limiter.acquire()
        response = genai.embed_content(
            model=settings.EMBEDDING_MODEL,
            content=text,
            task_type="retrieval_document"
        )
        return response["embedding"]

    async def index_repository(self, repo_name: str, local_path: Path) -> int:
        """
        Indexes a repository directory:
        1. Scans and chunks all files.
        2. Generates embeddings in batches.
        3. Stores in ChromaDB.
        """
        logger.info(f"Indexing repository '{repo_name}' from {local_path}...")
        chunks = self.scan_directory(local_path)
        if not chunks:
            logger.warning("No indexable code chunks found.")
            return 0

        collection = self.get_collection(repo_name)
        
        # Clear existing entries in the collection first to avoid duplicates/stale data
        # Note: ChromaDB doesn't have an easy "delete all" except deleting the collection or deleting by list of ids.
        # We can recreate the collection by deleting it first.
        try:
            self.chroma_client.delete_collection(sanitize_collection_name(repo_name))
        except Exception:
            pass # Collection might not exist yet
        
        collection = self.get_collection(repo_name)

        # Batch indexing to respect API limits and keep memory usage bounded
        batch_size = 50
        indexed_count = 0

        for i in range(0, len(chunks), batch_size):
            batch = chunks[i:i + batch_size]
            ids = []
            documents = []
            metadatas = []
            embeddings = []

            for idx, chunk in enumerate(batch):
                try:
                    # Generate embedding
                    embedding = await self._get_embedding(chunk.content)
                    
                    chunk_id = f"{chunk.file_path}_{chunk.start_line}_{chunk.end_line}"
                    ids.append(chunk_id)
                    documents.append(chunk.content)
                    embeddings.append(embedding)
                    metadatas.append({
                        "file_path": chunk.file_path,
                        "start_line": chunk.start_line,
                        "end_line": chunk.end_line,
                        "repo_name": repo_name
                    })
                except Exception as e:
                    logger.error(f"Failed to generate embedding for {chunk.file_path} (lines {chunk.start_line}-{chunk.end_line}): {e}")

            if ids:
                collection.add(
                    ids=ids,
                    embeddings=embeddings,
                    documents=documents,
                    metadatas=metadatas
                )
                indexed_count += len(ids)
                logger.info(f"Indexed {indexed_count}/{len(chunks)} chunks...")

        logger.info(f"Indexing completed for '{repo_name}'. Total chunks indexed: {indexed_count}")
        return indexed_count
