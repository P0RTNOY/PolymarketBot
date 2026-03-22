from abc import ABC, abstractmethod
from bot.execution.types import MarketSnapshot, TradeSignal

class Strategy(ABC):
    name: str

    @abstractmethod
    def evaluate(self, snapshot: MarketSnapshot) -> TradeSignal:
        raise NotImplementedError
