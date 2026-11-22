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
    store_search_cache_ttl_seconds: int = Field(
        default=86400,
        alias="STORE_SEARCH_CACHE_TTL_SECONDS",
    )
    min_match_similarity_score: float = Field(default=0.55, alias="MIN_MATCH_SIMILARITY_SCORE")

    # Local Ollama LLM Configuration (Optional)
    ollama_enabled: bool = Field(default=True, alias="OLLAMA_ENABLED")
    ollama_base_url: str = Field(default="http://localhost:11434", alias="OLLAMA_BASE_URL")
    ollama_model: str = Field(default="qwen3.5:latest", alias="OLLAMA_MODEL")
    ollama_timeout_seconds: float = Field(default=30.0, alias="OLLAMA_TIMEOUT_SECONDS")
    ollama_think: bool = Field(default=False, alias="OLLAMA_THINK")
    ollama_max_concurrency: int = Field(default=1, alias="OLLAMA_MAX_CONCURRENCY")

    # Gemini & Per-Service LLM Provider Configuration
    comparison_llm_provider: str = Field(default="ollama", alias="COMPARISON_LLM_PROVIDER")
    agent_llm_provider: str = Field(default="gemini", alias="AGENT_LLM_PROVIDER")
    embedding_provider: str = Field(default="local", alias="EMBEDDING_PROVIDER")
    gemini_api_key: Optional[str] = Field(default=None, alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-3.5-flash", alias="GEMINI_MODEL")
    gemini_embedding_model: str = Field(default="gemini-embedding-001", alias="GEMINI_EMBEDDING_MODEL")
    mcp_server_url: Optional[str] = Field(default=None, alias="MCP_SERVER_URL")

    # Security & Rate Limiting
    require_auth: bool = Field(default=True, alias="REQUIRE_AUTH")
    api_auth_token: Optional[str] = Field(default=None, alias="API_AUTH_TOKEN")
    rate_limit_per_minute: int = Field(default=60, alias="RATE_LIMIT_PER_MINUTE")
    max_new_users_per_day: int = Field(default=5, alias="MAX_NEW_USERS_PER_DAY")
    max_chats_per_user_per_day: int = Field(default=3, alias="MAX_CHATS_PER_USER_PER_DAY")

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
    relevance_dataset_path: Path = Field(
        default=base_dir / "data" / "relevance_training.jsonl",
        alias="RELEVANCE_DATASET_PATH",
    )
    langfuse_relevance_dataset: str = Field(
        default="grocery-relevance-classification",
        alias="LANGFUSE_RELEVANCE_DATASET",
    )
    translation_dataset_path: Path = Field(
        default=base_dir / "data" / "translation_dataset.jsonl",
        alias="TRANSLATION_DATASET_PATH",
    )
    langfuse_translation_dataset: str = Field(
        default="grocery-translation-accuracy",
        alias="LANGFUSE_TRANSLATION_DATASET",
    )

    # Users, Sessions & Google OAuth (Optional, Free Tier)
    users_db_path: Path = Field(
        default=base_dir / "data" / "users.db",
        alias="USERS_DB_PATH",
    )
    session_ttl_hours: int = Field(default=168, alias="SESSION_TTL_HOURS")
    google_client_id: Optional[str] = Field(default=None, alias="GOOGLE_CLIENT_ID")
    google_client_secret: Optional[str] = Field(default=None, alias="GOOGLE_CLIENT_SECRET")
    google_redirect_uri: Optional[str] = Field(default=None, alias="GOOGLE_REDIRECT_URI")


settings = AppSettings()
