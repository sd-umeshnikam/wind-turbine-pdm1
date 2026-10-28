"""Runtime configuration, read from WTPDM_* environment variables (12-factor)."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="WTPDM_", env_file=".env", extra="ignore")

    environment: str = "local"
    log_level: str = "INFO"

    database_url: str = "postgresql+psycopg://wtpdm:wtpdm@localhost:5434/wtpdm"
    mlflow_tracking_uri: str = "http://localhost:5001"

    # Raw CARE dataset (read-only) and the curated lake this platform writes.
    raw_data_root: Path = Path("/data/raw")
    lake_root: Path = Path("/data/lake")

    # Auth. The secret has no default outside tests: the API refuses to start without it.
    jwt_secret: SecretStr = SecretStr("")
    jwt_ttl_minutes: int = 480
    admin_username: str = "admin"
    admin_password: SecretStr = SecretStr("")

    # Replay of real SCADA history: simulated seconds advanced per wall-clock second.
    replay_speed: float = Field(default=60.0, gt=0)
    replay_tick_seconds: float = Field(default=10.0, gt=0)

    # Drift monitoring and retraining.
    drift_interval_minutes: int = Field(default=15, gt=0)
    drift_window_days: int = Field(default=30, gt=0)  # data time, per turbine
    retrain_cron: str = "0 2 * * 0"  # weekly, Sunday 02:00 (crontab syntax)
    retrain_cooldown_hours: float = 24.0  # min wall time between drift-triggered retrains of a farm
    retrain_auto_promote: bool = True  # False: a challenger that passes the gate waits for approval

    # Assistant (OpenAI-compatible endpoint, e.g. Groq).
    llm_api_key: SecretStr = SecretStr("")
    llm_base_url: str = "https://api.groq.com/openai/v1"
    llm_model: str = "openai/gpt-oss-120b"


@lru_cache
def get_settings() -> Settings:
    return Settings()
