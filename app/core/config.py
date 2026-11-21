from pathlib import Path
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    """Global application settings and configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # General
    app_name: str = "Grocery Price Comparator"
    environment: str = Field(default="development", alias="ENVIRONMENT")
    debug: bool = Field(default=False, alias="DEBUG")
    app_host: str = Field(default="0.0.0.0", alias="APP_HOST")
    app_port: int = Field(default=8000, alias="APP_PORT")
    default_language: str = Field(default="en", alias="DEFAULT_LANGUAGE")

    # Supermarket Credentials (Optional)
    rohlik_username: Optional[str] = Field(default=None, alias="ROHLIK_USERNAME")
    rohlik_password: Optional[str] = Field(default=None, alias="ROHLIK_PASSWORD")
    kosik_user_token: Optional[str] = Field(default=None, alias="KOSIK_USER_TOKEN")

    # Search & Comparison Configuration
    request_timeout_seconds: float = Field(default=10.0, alias="REQUEST_TIMEOUT_SECONDS")
    cache_ttl_seconds: int = Field(default=300, alias="CACHE_TTL_SECONDS")
    min_match_similarity_score: float = Field(default=0.55, alias="MIN_MATCH_SIMILARITY_SCORE")

    # Local Ollama LLM Configuration (Optional)
    ollama_enabled: bool = Field(default=True, alias="OLLAMA_ENABLED")
    ollama_base_url: str = Field(default="http://localhost:11434", alias="OLLAMA_BASE_URL")
    ollama_model: str = Field(default="qwen2.5-coder:latest", alias="OLLAMA_MODEL")
    ollama_timeout_seconds: float = Field(default=15.0, alias="OLLAMA_TIMEOUT_SECONDS")

    # File paths
    base_dir: Path = Path(__file__).resolve().parent.parent.parent
    staples_config_path: Path = base_dir / "config" / "staples.yaml"


settings = AppSettings()
