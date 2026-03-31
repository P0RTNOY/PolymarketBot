import unittest
import sys
import os
from datetime import datetime

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))

from scripts.compare_market_profiles import ProfileComparator

class TestProfileComparison(unittest.TestCase):
    def setUp(self):
        self.start = datetime(2026, 3, 22)
        self.end = datetime(2026, 3, 28)
        self.comparator = ProfileComparator(self.start, self.end)

    def test_ranking_logic_basic(self):
        # Mock results
        results = {
            "good_profile": {
                "profile_name": "good_profile",
                "comparison_eligible": True,
                "data_status": "comparable",
                "snapshot_quality": {"pct_snapshots_meeting_exec_conditions": 0.8, "p90_spread": 0.05},
                "funnel_quality": {"tradeable_to_exec_approved_rate": 0.5},
                "coverage": {"total_signals": 100},
                "profile_description": "A good profile"
            },
            "poor_profile": {
                "profile_name": "poor_profile",
                "comparison_eligible": True,
                "data_status": "comparable",
                "snapshot_quality": {"pct_snapshots_meeting_exec_conditions": 0.1, "p90_spread": 0.25}, # Penalty for spread
                "funnel_quality": {"tradeable_to_exec_approved_rate": 0.05},
                "coverage": {"total_signals": 10}, # Penalty for low volume
                "profile_description": "A poor profile"
            }
        }
        
        ranked_data = self.comparator._rank_profiles(results)
        ranked = ranked_data["ranked_profiles"]
        
        self.assertEqual(len(ranked), 2)
        self.assertEqual(ranked[0]["name"], "good_profile")
        self.assertGreater(ranked[0]["score"], ranked[1]["score"])

    def test_missing_data_handling(self):
        results = {
            "no_data_profile": {
                "profile_name": "no_data_profile",
                "comparison_eligible": False,
                "data_status": "no_data",
                "profile_description": "No data here"
            }
        }
        
        ranked_data = self.comparator._rank_profiles(results)
        self.assertEqual(len(ranked_data["ranked_profiles"]), 0)
        self.assertIn("No profiles were eligible", ranked_data["ranking_rationale"])

    def test_insufficient_data_eligibility(self):
        # 1. Low snapshots
        raw_low_snap = {
            "coverage": {"total_snapshots": 50, "total_signals": 20},
            "snapshot_quality": {},
            "opportunity_funnel": {},
            "failure_analysis": {},
            "universe_verdict": {}
        }
        res = self.comparator._process_result("test", "desc", raw_low_snap)
        self.assertFalse(res["comparison_eligible"])
        self.assertIn("Low snapshot count", res["eligibility_reason"])

        # 2. Low signals
        raw_low_sig = {
            "coverage": {"total_snapshots": 1000, "total_signals": 5},
            "snapshot_quality": {},
            "opportunity_funnel": {},
            "failure_analysis": {},
            "universe_verdict": {}
        }
        res = self.comparator._process_result("test", "desc", raw_low_sig)
        self.assertFalse(res["comparison_eligible"])
        self.assertIn("Low signal count", res["eligibility_reason"])

if __name__ == "__main__":
    unittest.main()
