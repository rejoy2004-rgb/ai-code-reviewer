import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock
from app.rag.indexer import RepositoryIndexer, sanitize_collection_name
from app.rag.retriever import RepositoryRetriever


def test_sanitize_collection_name():
    assert sanitize_collection_name("my-repo") == "my-repo"
    assert sanitize_collection_name("my.special/repo_name") == "my_special_repo_name"
    assert sanitize_collection_name("a") == "repo_a" # padding for short names


def test_chunk_file(tmp_path):
    test_file = tmp_path / "test.py"
    # Create 60 lines file
    content = "\n".join([f"line {i}" for i in range(1, 61)])
    test_file.write_text(content)
    
    indexer = RepositoryIndexer(chroma_dir=str(tmp_path / "chromadb"))
    chunks = indexer.chunk_file(test_file, "test.py", max_chunk_lines=30, overlap_lines=5)
    
    # 60 lines divided into chunks of 30 lines with 5 overlap.
    # Chunk 1: lines 1-30.
    # Chunk 2: lines 26-55.
    # Chunk 3: lines 51-60.
    assert len(chunks) == 3
    assert chunks[0].start_line == 1
    assert chunks[0].end_line == 30
    assert chunks[1].start_line == 26
    assert chunks[1].end_line == 55
    assert chunks[2].start_line == 51
    assert chunks[2].end_line == 60


@pytest.mark.asyncio
async def test_retrieve_similar_code(tmp_path):
    chroma_dir = tmp_path / "chromadb"
    retriever = RepositoryRetriever(chroma_dir=str(chroma_dir))
    
    mock_results = {
        "documents": [["def foo():\n    print('hello')"]],
        "metadatas": [[{"file_path": "main.py", "start_line": 1, "end_line": 2}]],
        "distances": [[0.15]]
    }
    
    # Mock Chroma collection query and Gemini embedding
    with patch.object(retriever.chroma_client, "get_collection") as mock_get_col, \
         patch.object(retriever, "_get_query_embedding", new_callable=AsyncMock) as mock_embed:
        
        mock_col = MagicMock()
        mock_col.query.return_value = mock_results
        mock_get_col.return_value = mock_col
        mock_embed.return_value = [0.1] * 768
        
        results = await retriever.retrieve_similar_code("owner/repo", "search query")
        
        assert len(results) == 1
        assert results[0]["file_path"] == "main.py"
        assert results[0]["content"] == "def foo():\n    print('hello')"
        assert results[0]["distance"] == 0.15
        mock_col.query.assert_called_once()
