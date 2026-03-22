import asyncio
from bot.execution.paper_trader import PaperTrader
from bot.data.repositories.signals import SignalRepository
from bot.data.repositories.paper import PaperRepository
from bot.data.repositories.snapshots import SnapshotRepository
from bot.execution.types import MarketSnapshot
from bot.data.session import SessionLocal
from bot.data.models import SignalRecord
from sqlalchemy import select

async def main() -> None:
    trader = PaperTrader()
    signal_repo = SignalRepository()
    paper_repo = PaperRepository()
    snap_repo = SnapshotRepository()

    print("[paper_trader] started")
    
    # We will track processed signals in memory to avoid duplicating orders 
    # (In a real app, we'd add 'processed' boolean to the DB or check existing paper orders)
    processed_signal_ids = set()

    while True:
        try:
            # 1. Fetch new signals
            latest_signals = signal_repo.get_latest_signals(limit=50)
            new_signals = []
            
            if latest_signals:
                from bot.risk.manager import RiskManager
                risk_manager = RiskManager()
                risk_context = paper_repo.get_risk_context()

            with SessionLocal() as session:
                for s in latest_signals:
                    if s.id not in processed_signal_ids:
                        class DummySignal:
                            pass
                        sig = DummySignal()
                        sig.id = s.id
                        sig.market_id = s.market_id
                        sig.token_id = s.token_id
                        sig.side = s.side
                        sig.market_prob = s.market_prob
                        sig.suggested_price = s.suggested_price
                        sig.suggested_size_usd = s.suggested_size_usd
                        sig.strategy_name = s.strategy_name
                        sig.edge = s.edge
                        
                        history = snap_repo.get_snapshot_history(s.market_id, limit=1)
                        if history:
                            sig.spread_at_entry = history[0].spread
                        else:
                            sig.spread_at_entry = 0.0
                        
                        from bot.data.repositories.markets import MarketRepository
                        m_repo = MarketRepository()
                        market_info = m_repo.get_market(s.market_id)
                        time_rem = 0.0
                        if market_info and market_info.end_time:
                            import datetime
                            now = datetime.datetime.now(datetime.timezone.utc)
                            delta = market_info.end_time - now
                            time_rem = max(0.0, delta.total_seconds() / 60.0)
                        sig.time_remaining_at_entry = time_rem
                        
                        is_approved, reason = risk_manager.approve(sig, risk_context)
                        if is_approved:
                            new_signals.append(sig)
                            signal_repo.update_eval_status(sig.id, "ACCEPTED", reason)
                            # Optimistically update context so batch doesn't breach limits
                            risk_context["open_count"] += 1
                            risk_context["notional_usd"] += sig.suggested_size_usd
                        else:
                            print(f"[paper_trader] Rejected signal {sig.id} - Reason: {reason}")
                            signal_repo.update_eval_status(sig.id, "REJECTED", reason)
                            
                        processed_signal_ids.add(s.id)

            if new_signals:
                trader.process_signals(new_signals)

            # 2. Simulate fills for open orders
            open_orders = paper_repo.get_open_orders()
            if open_orders:
                snapshots_map = {}
                for order in open_orders:
                    history = snap_repo.get_snapshot_history(order.market_id, limit=1)
                    if history:
                        h = history[0]
                        snap = MarketSnapshot(
                            market_id=h.market_id,
                            token_id=h.token_id,
                            question="",
                            best_bid=h.best_bid,
                            best_ask=h.best_ask,
                            midpoint=h.midpoint,
                            spread=h.spread,
                            bid_depth_usd=h.bid_depth_usd,
                            ask_depth_usd=h.ask_depth_usd,
                            timestamp=h.timestamp
                        )
                        snapshots_map[order.market_id] = snap
                
                trader.simulate_fills(open_orders, snapshots_map)

            await asyncio.sleep(5)
        except Exception as e:
            print("[paper_trader] ERROR:", str(e))
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())
