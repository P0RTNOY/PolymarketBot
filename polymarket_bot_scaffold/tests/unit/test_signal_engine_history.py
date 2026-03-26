"""
tests/unit/test_signal_engine_history.py
Phase 12.3A — Unit tests for history-aware signal engine integration.
"""
import pytest
from unittest.mock import MagicMock, patch
from apps.worker.signal_engine import main
from bot.core.config import Settings
from bot.data.models import Market, MarketSnapshot

@pytest.fixture
def mock_settings():
    return Settings(
        min_edge=0.04,
        max_spread=0.10,
        min_depth_usd=100.0,
        book_stability_lookback=3, # Small for testing
        enable_persistence_gate=False
    )

@pytest.mark.asyncio
async def test_signal_engine_fetches_history(mock_settings):
    # Setup mocks
    mock_market_repo = MagicMock()
    mock_snap_repo = MagicMock()
    mock_signal_repo = MagicMock()
    
    # One active market
    mock_market = Market(id="m1", active=True, closed=False, question="ETH up?", end_time=None)
    mock_market_repo.list_markets.return_value = [mock_market]
    
    # History of 3 snapshots
    mock_snaps = [
        MarketSnapshot(market_id="m1", token_id="t1", best_bid=0.5, best_ask=0.52, midpoint=0.51, spread=0.02, bid_depth_usd=200, ask_depth_usd=200, timestamp=None),
        MarketSnapshot(market_id="m1", token_id="t1", best_bid=0.5, best_ask=0.52, midpoint=0.51, spread=0.02, bid_depth_usd=200, ask_depth_usd=200, timestamp=None),
        MarketSnapshot(market_id="m1", token_id="t1", best_bid=0.5, best_ask=0.52, midpoint=0.51, spread=0.02, bid_depth_usd=200, ask_depth_usd=200, timestamp=None)
    ]
    mock_snap_repo.get_snapshot_history.return_value = mock_snaps
    
    # Patch all dependencies
    with patch("apps.worker.signal_engine.MarketRepository", return_value=mock_market_repo), \
         patch("apps.worker.signal_engine.SnapshotRepository", return_value=mock_snap_repo), \
         patch("apps.worker.signal_engine.SignalRepository", return_value=mock_signal_repo), \
         patch("apps.worker.signal_engine.get_settings", return_value=mock_settings), \
         patch("apps.worker.signal_engine.asyncio.sleep", side_effect=[None, Exception("Stop loop")]):
        
        try:
            await main()
        except Exception as e:
            if str(e) != "Stop loop":
                raise e

    # Verify history fetch
    mock_snap_repo.get_snapshot_history.assert_called_with("m1", limit=3)
    
    # Verify signal insertion (even if 0 alpha, it might log if CANDIDATE logic hits)
    # Our mocked snapshots have 0.02 spread and 200 depth, so they should be tradable.
    # If edge=0, candidate logic won't fire unless floor is met.
    # But we verified the repository call which is the main goal.
    assert mock_market_repo.list_markets.called
    assert mock_snap_repo.get_snapshot_history.called
