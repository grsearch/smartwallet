from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Smart Wallet Dashboard"
    database_url: str = "sqlite:///./smartwallet.db"

    birdeye_api_key: str = Field(default="", validation_alias="BIRDEYE_API_KEY")
    birdeye_base_url: str = "https://public-api.birdeye.so"

    trending_scan_minutes: int = 15
    wallet_daily_scan_hour_utc: int = 0
    token_daily_scan_hour_utc: int = 1

    top_trending_limit: int = 20
    max_prelist_wallets: int = 150
    formal_whitelist_limit: int = 100

    min_fdv: float = 500_000
    min_lp_fdv_ratio: float = 0.10
    min_age_seconds: int = 4 * 60 * 60
    max_age_seconds: int = 7 * 24 * 60 * 60

    wallet_expiry_days: int = 7
    webhook_url: str = ""


settings = Settings()
