from bot.execution.types import TradeSignal, MarketSnapshot
from bot.risk.manager import RiskManager
from bot.data.repositories.paper import PaperRepository
import uuid
import datetime

class PaperTrader:
    def __init__(self) -> None:
        self.risk = RiskManager()
        self.repo = PaperRepository()

    def process_signals(self, signals: list) -> None:
        for sig in signals:
            try:
                # Mock a snapshot for risk manager if needed, or modify risk manager.
                # Currently RiskManager is a stub that always approves.
                snapshot_stub = MarketSnapshot(
                    market_id=sig.market_id,
                    token_id=sig.token_id,
                    question="",
                    best_bid=0.0,
                    best_ask=0.0,
                    midpoint=sig.market_prob,
                    spread=0.0,
                    bid_depth_usd=0.0,
                    ask_depth_usd=0.0
                )
                approved, reason = self.risk.approve(sig, snapshot_stub)
                if not approved:
                    continue
                
                # Check if we already created an order for this signal
                # To prevent duplicates, we can rely on signal ID or just trust the worker.
                # Assuming worker passes NEW signals only.
                
                # Optional: grab the actual snapshot logic if it was passed.
                # Since apps/worker/paper_trader converts TradeSignal, we can append 
                # spread and end_time to DummySignal, or fetch it.
                # Assume sig has sig.spread_at_entry and sig.time_remaining_at_entry populated now.
                spread_val = getattr(sig, "spread_at_entry", 0.0)
                time_val = getattr(sig, "time_remaining_at_entry", 0.0)

                order_doc = {
                    "id": uuid.uuid4().hex,
                    "signal_id": sig.id,
                    "market_id": sig.market_id,
                    "token_id": sig.token_id,
                    "side": sig.side,
                    "price": sig.suggested_price,
                    "size_usd": sig.suggested_size_usd,
                    "status": "OPEN",
                    "created_at": datetime.datetime.now(datetime.timezone.utc),
                    "spread_at_entry": spread_val,
                    "time_remaining_at_entry": time_val,
                    "strategy_version": getattr(sig, 'strategy_name', 'unknown')
                }
                self.repo.insert_order(order_doc)
                print(f"[paper_trader] Placed limit order: side={sig.side} price={sig.suggested_price} size={sig.suggested_size_usd}")
            except Exception as e:
                print(f"[paper_trader] Error processing signal {sig.id}: {e}")

    def simulate_fills(self, open_orders: list, latest_snapshots: dict[str, MarketSnapshot], db_snapshots: dict = None) -> None:
        import random
        from datetime import datetime, timezone, timedelta
        
        now = datetime.now(timezone.utc)
        
        for order in open_orders:
            # 1. Cancel Timeout Protection
            # If the order has been sitting unfilled (OPEN or PARTIAL) for 15+ mins, cancel it
            if order.created_at and (now - order.created_at.replace(tzinfo=timezone.utc)) > timedelta(minutes=15):
                self.repo.update_order_status_only(order.id, "CANCELED")
                print(f"[paper_trader] CANCELED {order.id}: timeout exceeded")
                continue

            snap = latest_snapshots.get(order.market_id)
            if not snap:
                continue

            # 2. Stale Data Protection
            if db_snapshots and order.market_id in db_snapshots:
                db_snap = db_snapshots[order.market_id]
                if db_snap.timestamp:
                    snap_time = db_snap.timestamp.replace(tzinfo=timezone.utc)
                    if (now - snap_time) > timedelta(seconds=30):
                        continue # Stale book

            # Map the market price relative to our side. BUY_NO means taking the opposite side of the book
            if order.side == "BUY_YES":
                market_ask = snap.best_ask
                market_bid = snap.best_bid
            else:
                market_ask = 1.0 - snap.best_bid
                market_bid = 1.0 - snap.best_ask

            if market_ask <= 0 or market_bid <= 0 or order.price <= 0:
                continue

            is_aggressive = order.price >= market_ask
            is_touching = abs(order.price - market_ask) < 0.005

            fill_amount = 0.0
            fill_price = order.price
            
            # 3. Latency Slippage Penalty for Aggressive Orders
            if is_aggressive:
                slippage = 0.0
                if snap.spread > 0.05:
                    slippage = 0.01
                
                executed_price = min(order.price, market_ask + slippage)
                available_depth_proxy = 500.0 # Assuming $500 top of book depth since we don't persist depth
                amount_to_fill = min(order.size_usd - order.filled_size_usd, available_depth_proxy)
                
                if amount_to_fill > 0:
                    fill_amount = amount_to_fill
                    fill_price = executed_price

            # 4. Queue Penalty for Passive Orders
            elif is_touching:
                # 20% priority chance of filling a chunk of size if touched but not crossed
                if random.random() < 0.20:
                    amount_to_fill = (order.size_usd - order.filled_size_usd) * 0.25
                    amount_to_fill = max(10.0, min(amount_to_fill, order.size_usd - order.filled_size_usd)) # Force min $10 partially filled
                    fill_amount = amount_to_fill
                    fill_price = order.price
                    print(f"[paper_trader] ORDER PARTIAL FILL: queue penalty applied. Filled ${fill_amount:.2f}")

            if fill_amount > 0:
                is_final = (order.filled_size_usd + fill_amount) >= order.size_usd
                self.repo.apply_fill(order.id, added_usd=fill_amount, fill_price=fill_price, is_final=is_final, filled_at=now)
                print(f"[paper_trader] Order {'FILLED' if is_final else 'PARTIAL'}! {order.side} amount=${fill_amount:.2f} at {fill_price:.3f}")
