from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from src.config import Settings, _BUILTIN_LICENCE


def test_blank_licence_env_does_not_force_offline(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    env = tmp_path / ".env"
    env.write_text(
        "MAIRUI_OFFLINE=0\nMAIRUI_LICENCE=\nMAIRUI_LICENCES=\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("MAIRUI_OFFLINE", raising=False)
    monkeypatch.delenv("MAIRUI_LICENCE", raising=False)
    monkeypatch.delenv("MAIRUI_LICENCES", raising=False)

    class LocalSettings(Settings):
        model_config = SettingsConfigDict(
            env_file=env,
            env_file_encoding="utf-8",
            extra="ignore",
        )

    cfg = LocalSettings()
    assert cfg.mairui_offline is False
    assert _BUILTIN_LICENCE in cfg.licence_chain
    assert cfg.use_live_market is True
    assert cfg.offline_reason == ""


def test_mairui_offline_forces_fixtures(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    env = tmp_path / ".env"
    env.write_text(
        "MAIRUI_OFFLINE=1\nMAIRUI_LICENCE=LIVE-KEY-1\nMAIRUI_LICENCES=\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("MAIRUI_OFFLINE", raising=False)
    monkeypatch.delenv("MAIRUI_LICENCE", raising=False)
    monkeypatch.delenv("MAIRUI_LICENCES", raising=False)

    class LocalSettings(Settings):
        model_config = SettingsConfigDict(
            env_file=env,
            env_file_encoding="utf-8",
            extra="ignore",
        )

    cfg = LocalSettings()
    assert cfg.use_live_market is False
    assert "MAIRUI_OFFLINE=1" in cfg.offline_reason
