from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_secret: str = "change-this-local-secret"
    app_host: str = "127.0.0.1"
    app_port: int = 8765
    bootstrap_user: str = "hanish"
    bootstrap_password: str = "change-me"
    mairui_licence: str = ""
    mairui_offline: bool = True
    mairui_base: str = "https://api.mairuiapi.com"
    demo_licence: str = "LICENCE-66D8-9F96-0C7F0FBCD073"
    data_dir: Path = ROOT / "data"
    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    query_sync_limit: int = 40

    @property
    def db_path(self) -> Path:
        return self.data_dir / "app.db"

    @property
    def artifact_dir(self) -> Path:
        return self.data_dir / "artifacts" / "query"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
settings.artifact_dir.mkdir(parents=True, exist_ok=True)
settings.cache_dir.mkdir(parents=True, exist_ok=True)
