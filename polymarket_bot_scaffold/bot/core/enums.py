from enum import StrEnum

class TradingMode(StrEnum):
    PAPER = "paper"
    LIVE = "live"

class OrderStatus(StrEnum):
    CREATED = "created"
    OPEN = "open"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
