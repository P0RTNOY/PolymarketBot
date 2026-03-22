from sqlalchemy import select
from bot.data.models import Market, OutcomeToken
from bot.data.session import SessionLocal
from datetime import datetime

class MarketRepository:
    def list_markets(self) -> list[Market]:
        with SessionLocal() as session:
            return list(session.scalars(select(Market)))

    def upsert_many(self, markets: list[dict]) -> None:
        with SessionLocal() as session:
            for item in markets:
                end_date_str = item.get("endDate")
                end_time = None
                if end_date_str:
                    try:
                        end_time = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
                    except Exception:
                        pass

                row = session.get(Market, item["id"])
                if row is None:
                    row = Market(
                        id=item["id"],
                        condition_id=item.get("condition_id"),
                        question=item.get("question", ""),
                        category=item.get("category"),
                        active=item.get("active", True),
                        closed=item.get("closed", False),
                        end_time=end_time,
                        raw_json=item,
                    )
                    session.add(row)
                else:
                    row.question = item.get("question", row.question)
                    row.category = item.get("category", row.category)
                    row.active = item.get("active", row.active)
                    row.closed = item.get("closed", row.closed)
                    row.end_time = end_time if end_time else row.end_time
                    row.raw_json = item

                # Handle tokens if present in the item
                tokens = item.get("tokens", [])
                for token_data in tokens:
                    token_id = token_data.get("token_id")
                    if not token_id:
                        continue
                    
                    token_row = session.get(OutcomeToken, token_id)
                    if token_row is None:
                        token_row = OutcomeToken(
                            token_id=token_id,
                            market_id=item["id"],
                            outcome_name=token_data.get("outcome", "")
                        )
                        session.add(token_row)
                    else:
                        token_row.outcome_name = token_data.get("outcome", token_row.outcome_name)
            session.commit()

    def get_unresolved_markets(self) -> list[Market]:
        with SessionLocal() as session:
            stmt = select(Market).where(Market.status != "RESOLVED")
            return list(session.scalars(stmt))

    def mark_market_resolved(self, market_id: str, winning_token_id: str) -> None:
        with SessionLocal() as session:
            market = session.get(Market, market_id)
            if market:
                market.status = "RESOLVED"
                market.winning_token_id = winning_token_id
                session.commit()
