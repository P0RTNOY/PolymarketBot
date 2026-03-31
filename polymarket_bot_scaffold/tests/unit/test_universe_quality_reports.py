
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch
from bot.data.repositories.reports import ReportRepository
from bot.data.models import MarketSnapshot, SignalRecord
from bot.analytics.candidate_buckets import TRADEABLE, CANDIDATE

class TestUniverseQualityReports(unittest.TestCase):
    def setUp(self):
        self.repo = ReportRepository()
        self.now = datetime.now(timezone.utc)

    @patch("bot.data.repositories.reports.SessionLocal")
    @patch("bot.data.repositories.reports.get_settings")
    def test_get_universe_quality_basic(self, mock_settings, mock_session_local):
        # Mock settings
        mock_settings.return_value = MagicMock(
            max_spread=0.02,
            min_depth_usd=500,
        )

        # Mock database session
        mock_session = MagicMock()
        mock_session_local.return_value.__enter__.return_value = mock_session

        # Mock snapshots (2 snapshots, one good, one bad)
        s1 = MarketSnapshot(
            market_id="m1", 
            token_id="t1", 
            spread=0.01, 
            bid_depth_usd=300, 
            ask_depth_usd=300, 
            timestamp=self.now
        )
        s2 = MarketSnapshot(
            market_id="m1", 
            token_id="t1", 
            spread=0.05, 
            bid_depth_usd=100, 
            ask_depth_usd=100, 
            timestamp=self.now
        )
        
        # Mock signals (1 tradeable signal, 1 candidate)
        sig1 = SignalRecord(
            market_id="m1",
            token_id="t1",
            strategy_name="version1",
            candidate_status=TRADEABLE,
            exec_approved=True,
            eval_status="ACCEPTED",
            timestamp=self.now,
            exec_stability_score=0.9,
            exec_recent_tradable_ratio=1.0,
            exec_consecutive_tradable_snapshots=5,
            exec_stability_label="stable"
        )
        
        mock_session.scalars.side_effect = [
            MagicMock(all=lambda: [s1, s2]), # snapshots
            MagicMock(all=lambda: [sig1])   # signals
        ]

        report = self.repo.get_universe_quality(group_by="total")
        
        self.assertIn("total", report)
        data = report["total"]
        
        # Coverage
        self.assertEqual(data["coverage"]["total_snapshots"], 2)
        self.assertEqual(data["coverage"]["total_signals"], 1)
        
        # Snapshot Quality
        sq = data["snapshot_quality"]
        self.assertAlmostEqual(sq["median_spread"], 0.03) # median of 0.01, 0.05
        self.assertEqual(sq["pct_snapshots_meeting_exec_conditions"], 0.5) # only s1 is ok
        
        # Funnel
        fn = data["opportunity_funnel"]
        self.assertEqual(fn["total_tradeable"], 1)
        self.assertEqual(fn["tradeable_to_exec_approved_rate"], 1.0)
        
        # Verdict
        verdict = data["universe_verdict"]
        self.assertEqual(verdict["universe_status"], "viable")

if __name__ == "__main__":
    unittest.main()
