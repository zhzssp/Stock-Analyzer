from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent

_BUILTIN_LICENCE = "2FE37018-1B80-4185-91C5-05D4799A4572"
_BUILTIN_LICENCES = "0911733C-31DD-454C-ADCA-5CC002806939"


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
    # 主证书；可与 mairui_licences 组成队列（当日 429 自动换下一张）。
    mairui_licence: str = _BUILTIN_LICENCE
    mairui_licences: str = _BUILTIN_LICENCES
    # True 才用 src/market/fixtures.py 喂工作台。样例文件保留，pytest 仍会设 MAIRUI_OFFLINE=1。
    mairui_offline: bool = False
    mairui_base: str = "https://api.mairuiapi.com"
    demo_licence: str = "LICENCE-66D8-9F96-0C7F0FBCD073"
    data_dir: Path = ROOT / "data"
    llm_provider: str = "deepseek"
    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_model: str = "deepseek-flash"
    llm_timeout: float = 45.0
    alert_webhook: str = ""
    query_sync_limit: int = 40
    cache_max_mb: float = 300
    artifact_keep: int = 20
    bars_max: int = 500
    alerts_log_max_mb: float = 2
    clock_dir: str = ""
    clock_interval_sec: int = 300

    @field_validator("mairui_licence", mode="before")
    @classmethod
    def blank_primary_licence(cls, value):
        if value is None or (isinstance(value, str) and not value.strip()):
            return _BUILTIN_LICENCE
        return value

    @field_validator("mairui_licences", mode="before")
    @classmethod
    def blank_backup_licences(cls, value):
        if value is None or (isinstance(value, str) and not value.strip()):
            return _BUILTIN_LICENCES
        return value

    @property
    def licence_chain(self) -> list[str]:
        from src.market.licence_pool import parse_licences

        return parse_licences(self.mairui_licence, self.mairui_licences)

    @property
    def fixtures_enabled(self) -> bool:
        return bool(self.mairui_offline)

    @property
    def use_live_market(self) -> bool:
        """Live API when MAIRUI_OFFLINE=0 and .env 或本机证书池至少有一张证。"""
        if self.mairui_offline:
            return False
        if self.licence_chain:
            return True
        from src.market.licence_registry import LicenceRegistry

        return LicenceRegistry.shared().has_any_licence()

    @property
    def offline_reason(self) -> str:
        if self.mairui_offline:
            return "MAIRUI_OFFLINE=1，工作台强制使用内置样例"
        if self.use_live_market:
            return ""
        return "未配置有效麦蕊证书（.env 与本机证书池均为空）"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "app.db"

    @property
    def artifact_dir(self) -> Path:
        return self.data_dir / "artifacts" / "query"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def cache_max_bytes(self) -> int:
        return max(1, int(self.cache_max_mb * 1024 * 1024))

    @property
    def alerts_log_max_bytes(self) -> int:
        return max(64 * 1024, int(self.alerts_log_max_mb * 1024 * 1024))


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
settings.artifact_dir.mkdir(parents=True, exist_ok=True)
settings.cache_dir.mkdir(parents=True, exist_ok=True)
