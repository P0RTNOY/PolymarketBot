from sqlalchemy import select, desc
from bot.data.models import MarketSnapshot
from bot.data.session import SessionLocal
import uuid
from datetime import datetime, timezone

class SnapshotRepository:
    def insert_snapshot(self, snapshot_data: dict) -> MarketSnapshot:
        with SessionLocal() as session:
            snapshot = MarketSnapshot(
                id=str(uuid.uuid4()),
                market_id=snapshot_data["market_id"],
                token_id=snapshot_data["token_id"],
                best_bid=snapshot_data.get("best_bid", 0.0),
                best_ask=snapshot_data.get("best_ask", 0.0),
                midpoint=snapshot_data.get("midpoint", 0.0),
                spread=snapshot_data.get("spread", 0.0),
                bid_depth_usd=snapshot_data.get("bid_depth_usd", 0.0),
                ask_depth_usd=snapshot_data.get("ask_depth_usd", 0.0),
                timestamp=snapshot_data.get("timestamp", datetime.now(timezone.utc)),
            )
            session.add(snapshot)
            session.commit()
            session.refresh(snapshot)
            return snapshot

    def get_latest_snapshots(self, limit: int = 20) -> list[MarketSnapshot]:
        with SessionLocal() as session:
            stmt = select(MarketSnapshot).order_by(desc(MarketSnapshot.timestamp)).limit(limit)
            return list(session.scalars(stmt))

    def get_snapshot_history(
        self, market_id: str, token_id: str = None, limit: int = 5
    ) -> list[MarketSnapshot]:
        """Fetch chronological history for a market/token."""
        with SessionLocal() as session:
            stmt = select(MarketSnapshot).where(MarketSnapshot.market_id == market_id)
            if token_id:
                stmt = stmt.where(MarketSnapshot.token_id == token_id)

            # Important: fetch desc to get the most recent N, 
            # but we usually want to return them in ASC (chronological) order for time-series logic.
            # We fetch DESC here and reverse later to be safe with the limit.
            stmt = stmt.order_by(desc(MarketSnapshot.timestamp)).limit(limit)
            results = list(session.scalars(stmt))
            results.reverse()  # Return oldest first (chronological)
            return results

    def get_snapshots_in_range(self, start: datetime, end: datetime) -> list[MarketSnapshot]:
        """Return all snapshots in [start, end], ordered token-first then chronologically for replay."""
        with SessionLocal() as session:
            stmt = (
                select(MarketSnapshot)
                .where(MarketSnapshot.timestamp >= start)
                .where(MarketSnapshot.timestamp <= end)
                .order_by(MarketSnapshot.token_id, MarketSnapshot.timestamp.asc())
            )
            return list(session.scalars(stmt))
