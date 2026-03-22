import asyncio
from bot.core.config import get_settings
from bot.execution.types import MarketSnapshot
from bot.strategies.eth_direction_15m import ETHDirection15mStrategy
from bot.strategies.eth_direction_15m_v2 import ETHDirection15mV2Strategy
from bot.data.repositories.markets import MarketRepository
from bot.data.repositories.snapshots import SnapshotRepository
from bot.data.repositories.signals import SignalRepository

async def main() -> None:
    settings = get_settings()
    strategies = [ETHDirection15mStrategy(), ETHDirection15mV2Strategy()]
    market_repo = MarketRepository()
    snapshot_repo = SnapshotRepository()
    signal_repo = SignalRepository()

    print("[signal_engine] started")
    print(f"[signal_engine] running {len(strategies)} strategies: {[s.name for s in strategies]}")
    while True:
        try:
            markets = market_repo.list_markets()
            active_markets = [m for m in markets if m.active and not m.closed]
            
            for m in active_markets:
                history = snapshot_repo.get_snapshot_history(m.id, limit=2)
                if not history:
                    continue
                
                current_db = history[0]
                prev_db = history[1] if len(history) > 1 else None

                current_exec = MarketSnapshot(
                    market_id=current_db.market_id,
                    token_id=current_db.token_id,
                    question=m.question,
                    best_bid=current_db.best_bid,
                    best_ask=current_db.best_ask,
                    midpoint=current_db.midpoint,
                    spread=current_db.spread,
                    bid_depth_usd=current_db.bid_depth_usd,
                    ask_depth_usd=current_db.ask_depth_usd,
                    timestamp=current_db.timestamp,
                    end_time=m.end_time
                )

                prev_exec = None
                if prev_db:
                    prev_exec = MarketSnapshot(
                        market_id=prev_db.market_id,
                        token_id=prev_db.token_id,
                        question=m.question,
                        best_bid=prev_db.best_bid,
                        best_ask=prev_db.best_ask,
                        midpoint=prev_db.midpoint,
                        spread=prev_db.spread,
                        bid_depth_usd=prev_db.bid_depth_usd,
                        ask_depth_usd=prev_db.ask_depth_usd,
                        timestamp=prev_db.timestamp,
                        end_time=m.end_time
                    )

                for strategy in strategies:
                    signal = strategy.evaluate(current_exec, prev_exec)
                    if signal:
                        signal_dict = signal.model_dump()
                        signal_repo.insert_signal(signal_dict)
                        print(f"[signal_engine] [{strategy.name}] emitted signal for {m.id} | side={signal.side} edge={signal.edge:.4f}")

            await asyncio.sleep(5)
            
        except Exception as e:
            print("[signal_engine] ERROR:", str(e))
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())

