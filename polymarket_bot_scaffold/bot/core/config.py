from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "dev"
    app_name: str = "polymarket-bot"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    database_url: str = "sqlite+pysqlite:///./polymarket_bot.db"
    redis_url: str = "redis://localhost:6379/0"

    live_trading_enabled: bool = False
    paper_trading_enabled: bool = True
    panic_stop: bool = False

    max_order_usd: float = 10.0
    max_market_exposure_usd: float = 20.0
    max_notional_exposure_usd: float = 100.0
    max_open_positions: int = 5
    max_daily_loss_usd: float = 30.0
    cooldown_after_losses: int = 3
    cooldown_mins: float = 60.0
    min_edge: float = 0.04
    max_spread: float = 0.08
    min_depth_usd: float = 100.0
    signal_staleness_seconds: int = 15
    min_time_to_close_mins: float = 2.0

    # Phase 12.3A: Book Stability & Persistence
    book_stability_lookback: int = 5
    book_stability_required: int = 3
    min_tradable_streak_seconds: int = 20
    max_spread_jump: float = 0.05
    enable_persistence_gate: bool = False

    polymarket_api_base: str = "https://example.invalid"
    polymarket_wss_base: str = "wss://example.invalid/ws"
    polymarket_private_key: str = ""
    polymarket_api_key: str = ""
    polymarket_api_secret: str = ""
    polymarket_passphrase: str = ""

@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
