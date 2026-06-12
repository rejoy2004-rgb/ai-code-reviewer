import os
from unittest import mock
from app.config.settings import Settings


def test_settings_load():
    with mock.patch.dict(os.environ, {
        "GEMINI_API_KEY": "test-gemini-key",
        "GITHUB_TOKEN": "test-github-token",
        "GITHUB_WEBHOOK_SECRET": "test-webhook-secret",
        "CHROMADB_DIR": "./test_chroma",
        "DATABASE_URL": "sqlite:///./test_db.db"
    }):
        test_settings = Settings()
        assert test_settings.GEMINI_API_KEY == "test-gemini-key"
        assert test_settings.GITHUB_TOKEN == "test-github-token"
        assert test_settings.GITHUB_WEBHOOK_SECRET == "test-webhook-secret"
        assert test_settings.CHROMADB_DIR == "./test_chroma"
        assert test_settings.DATABASE_URL == "sqlite:///./test_db.db"
