from bot.execution.types import MarketSnapshot
from bot.strategies.eth_direction_15m import ETHDirection15mStrategy
from bot.risk.manager import RiskManager

def test_risk_approves_reasonable_signal() -> None:
    snapshot = MarketSnapshot.example()
    signal = ETHDirection15mStrategy().evaluate(snapshot)
    approved, _ = RiskManager().approve(signal, snapshot)
    assert isinstance(approved, bool)
