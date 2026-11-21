from pathlib import Path
from typing import List, Optional
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
    ollama_model: str = Field(default="qwen3.5:latest", alias="OLLAMA_MODEL")
    ollama_timeout_seconds: float = Field(default=30.0, alias="OLLAMA_TIMEOUT_SECONDS")
    ollama_think: bool = Field(default=False, alias="OLLAMA_THINK")
    ollama_max_concurrency: int = Field(default=1, alias="OLLAMA_MAX_CONCURRENCY")

    # Gemini & MCP/A2A Agent Configuration
    gemini_api_key: Optional[str] = Field(default=None, alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-3.5-flash", alias="GEMINI_MODEL")
    mcp_server_url: Optional[str] = Field(default=None, alias="MCP_SERVER_URL")

    # Language & Translation Cache Configuration
    default_catalog_language: str = Field(default="cs", alias="DEFAULT_CATALOG_LANGUAGE")
    supported_languages: List[str] = Field(default=["en", "cs"], alias="SUPPORTED_LANGUAGES")

    # Langfuse Monitoring Configuration (Optional)
    langfuse_enabled: bool = Field(default=False, alias="LANGFUSE_ENABLED")
    langfuse_public_key: Optional[str] = Field(default=None, alias="LANGFUSE_PUBLIC_KEY")
    langfuse_secret_key: Optional[str] = Field(default=None, alias="LANGFUSE_SECRET_KEY")
    langfuse_host: str = Field(default="https://cloud.langfuse.com", alias="LANGFUSE_HOST")

    # File paths
    base_dir: Path = Path(__file__).resolve().parent.parent.parent
    staples_config_path: Path = base_dir / "config" / "staples.yaml"
    tracked_groceries_config_path: Path = base_dir / "config" / "tracked_groceries.yaml"
    translation_db_path: Path = Field(
        default=base_dir / "data" / "translations.db",
        alias="TRANSLATION_DB_PATH",
    )
    price_history_db_path: Path = Field(
        default=base_dir / "data" / "price_history.db",
        alias="PRICE_HISTORY_DB_PATH",
    )


settings = AppSettings()
