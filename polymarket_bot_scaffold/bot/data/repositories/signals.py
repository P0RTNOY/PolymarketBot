from datetime import datetime
from sqlalchemy import select
from bot.data.models import SignalRecord
from bot.data.session import SessionLocal
from bot.analytics.candidate_buckets import EDGE_BUCKET_LABELS

class SignalRepository:
    def insert_signal(self, signal_data: dict) -> None:
        with SessionLocal() as session:
            record = SignalRecord(
                id=signal_data["id"],
                strategy_name=signal_data["strategy_name"],
                market_id=signal_data["market_id"],
                token_id=signal_data["token_id"],
                side=signal_data["side"],
                market_prob=signal_data["market_prob"],
                model_prob=signal_data["model_prob"],
                edge=signal_data["edge"],
                confidence=signal_data["confidence"],
                suggested_price=signal_data["suggested_price"],
                suggested_size_usd=signal_data["suggested_size_usd"],
                reason=signal_data["reason"],
                # Phase 12.0 optional enrichment fields
                alpha_score=signal_data.get("alpha_score"),
                exec_approved=signal_data.get("exec_approved"),
                exec_reasons=signal_data.get("exec_reasons"),
                risk_approved=signal_data.get("risk_approved"),
                risk_reasons=signal_data.get("risk_reasons"),
                features_json=signal_data.get("features_json"),
                # Phase 12.2 execution tradability score
                exec_tradability_score=signal_data.get("exec_tradability_score"),
                # Phase 12.1 candidate logging fields
                candidate_status=signal_data.get("candidate_status"),
                edge_bucket=signal_data.get("edge_bucket"),
            )
            session.add(record)
            session.commit()

    def get_candidates_by_edge_bucket(
        self,
        since: datetime,
        strategy_name: str | None = None,
    ) -> dict[str, int]:
        """
        Return candidate counts keyed by edge_bucket label.
        Includes ALL candidate_status values (CANDIDATE + TRADEABLE).

        Args:
            since:          Only count signals on or after this datetime.
            strategy_name:  Optional filter by strategy.

        Returns:
            Dict mapping each EDGE_BUCKET_LABEL to count (0 if none).
        """
        with SessionLocal() as session:
            stmt = (
                select(SignalRecord.edge_bucket)
                .where(SignalRecord.timestamp >= since)
                .where(SignalRecord.candidate_status.is_not(None))
            )
            if strategy_name:
                stmt = stmt.where(SignalRecord.strategy_name == strategy_name)

            rows = list(session.scalars(stmt))

        counts: dict[str, int] = {label: 0 for label in EDGE_BUCKET_LABELS}
        for bucket in rows:
            if bucket and bucket in counts:
                counts[bucket] += 1
        return counts


    def update_eval_status(self, signal_id: str, status: str, reason: str | None = None) -> None:
        with SessionLocal() as session:
            record = session.get(SignalRecord, signal_id)
            if record:
                record.eval_status = status
                record.eval_reason = reason
                session.commit()

    def get_latest_signals(self, limit: int = 50) -> list[SignalRecord]:
        with SessionLocal() as session:
            stmt = select(SignalRecord).order_by(SignalRecord.timestamp.desc()).limit(limit)
            return list(session.scalars(stmt))
