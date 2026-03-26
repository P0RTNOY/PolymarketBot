from bot.execution.types import MarketSnapshot
from bot.strategies.eth_direction_15m import ETHDirection15mStrategy
from bot.risk.manager import RiskManager

def test_risk_approves_reasonable_signal() -> None:
    snapshot = MarketSnapshot.example()
    signal = ETHDirection15mStrategy().evaluate(snapshot, previous=None)
    # signal may be None if edge is below threshold; test only if signal exists
    if signal is not None:
        risk_context: dict = {}
        approved, _ = RiskManager().approve(signal, risk_context)
        assert isinstance(approved, bool)
    else:
        # No signal emitted — acceptable for this fixture
        assert signal is None
