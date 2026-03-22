from bot.clients.polymarket_trading import PolymarketTradingClient
from bot.execution.types import TradeSignal

class LiveExecutor:
    def __init__(self) -> None:
        self.client = PolymarketTradingClient()

    async def submit(self, signal: TradeSignal) -> dict:
        return await self.client.create_limit_order(
            token_id=signal.token_id,
            side=signal.side,
            price=signal.suggested_price,
            size_usd=signal.suggested_size_usd,
        )
