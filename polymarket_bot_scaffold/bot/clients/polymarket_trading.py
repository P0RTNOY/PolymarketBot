from bot.core.config import get_settings

class PolymarketTradingClient:
    def __init__(self) -> None:
        self.settings = get_settings()

    def assert_live_ready(self) -> None:
        if not self.settings.live_trading_enabled:
            raise RuntimeError("Live trading is disabled.")
        if not self.settings.polymarket_private_key:
            raise RuntimeError("Missing private key.")
        if not self.settings.polymarket_api_key:
            raise RuntimeError("Missing API key.")

    async def create_limit_order(self, *, token_id: str, side: str, price: float, size_usd: float) -> dict:
        self.assert_live_ready()
        # Replace with signed-order flow using official Polymarket trading client / auth flow.
        return {
            "status": "submitted",
            "token_id": token_id,
            "side": side,
            "price": price,
            "size_usd": size_usd,
        }
