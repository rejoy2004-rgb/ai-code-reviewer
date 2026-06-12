import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Gemini Settings
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.5-flash"
    EMBEDDING_MODEL: str = "text-embedding-001"

    # GitHub Settings
    GITHUB_TOKEN: str = ""
    GITHUB_WEBHOOK_SECRET: str = ""

    # Slack Settings
    SLACK_WEBHOOK_URL: str | None = None

    # Storage Settings
    CHROMADB_DIR: str = "./data/chromadb"
    DATABASE_URL: str = "sqlite:///./data/reviews.db"

    # Server Settings
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    LOG_LEVEL: str = "info"

    @property
    def db_dir(self) -> Path:
        """Helper to ensure and return database directory."""
        db_path = self.DATABASE_URL.replace("sqlite:///", "")
        path = Path(db_path).parent
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def chroma_dir(self) -> Path:
        """Helper to ensure and return ChromaDB directory."""
        path = Path(self.CHROMADB_DIR)
        path.mkdir(parents=True, exist_ok=True)
        return path


settings = Settings()
# Initialize directories upon import
settings.db_dir
settings.chroma_dir
