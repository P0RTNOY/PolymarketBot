from sqlalchemy import select
from bot.data.models import SignalRecord
from bot.data.session import SessionLocal

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
                reason=signal_data["reason"]
            )
            session.add(record)
            session.commit()

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
