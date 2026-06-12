import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # =========================
    # OpenRouter Settings
    # =========================
    OPENROUTER_API_KEY: str = ""
    OPENROUTER_MODEL: str = "deepseek/deepseek-chat-v3"

    # =========================
    # Embeddings (Local)
    # =========================
    EMBEDDING_MODEL: str = "BAAI/bge-small-en-v1.5"

    # =========================
    # GitHub Settings
    # =========================
    GITHUB_TOKEN: str = ""
    GITHUB_WEBHOOK_SECRET: str = ""

    # =========================
    # Slack Settings
    # =========================
    SLACK_WEBHOOK_URL: str | None = None

    # =========================
    # Storage Settings
    # =========================
    CHROMADB_DIR: str = "./data/chromadb"
    DATABASE_URL: str = "sqlite:///./data/reviews.db"

    # =========================
    # Server Settings
    # =========================
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    LOG_LEVEL: str = "info"

    @property
    def db_dir(self) -> Path:
        db_path = self.DATABASE_URL.replace("sqlite:///", "")
        path = Path(db_path).parent
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def chroma_dir(self) -> Path:
        path = Path(self.CHROMADB_DIR)
        path.mkdir(parents=True, exist_ok=True)
        return path


settings = Settings()

# Initialize directories
settings.db_dir
settings.chroma_dir