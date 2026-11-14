"""Application configuration using Pydantic Settings."""

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Server settings
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    ENVIRONMENT: str = "development"

    # Database
    DATABASE_PATH: Path = BASE_DIR / "ehr_intelligence.db"

    # ChromaDB
    CHROMA_PERSIST_DIR: Path = BASE_DIR / "chroma_data"
    EMBEDDING_MODEL_NAME: str = "all-MiniLM-L6-v2"

    # LLM Settings
    LLM_PROVIDER: str = "mock"  # mock, anthropic, openai
    ANTHROPIC_API_KEY: str | None = None
    OPENAI_API_KEY: str | None = None


settings = Settings()

