from dataclasses import dataclass

@dataclass
class Position:
    token_id: str
    net_shares: float = 0.0
    avg_cost: float = 0.0
    realized_pnl_usd: float = 0.0
