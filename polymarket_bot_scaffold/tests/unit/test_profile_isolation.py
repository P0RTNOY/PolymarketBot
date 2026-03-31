import unittest
import sys
import shutil
import json
from pathlib import Path
from datetime import date

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from bot.core.paths import (
    get_profile_results_dir,
    get_profile_manifest_path,
    get_profile_summary_path,
    resolve_daily_output_paths
)
from scripts.experiment_config import compute_config_hash, write_manifest
from scripts.run_daily_research import check_manifest_and_warn

class TestProfileIsolation(unittest.TestCase):
    def setUp(self):
        self.test_profile = "test_challenger"
        self.results_base = PROJECT_ROOT / "results" / "profiles" / self.test_profile
        
    def tearDown(self):
        # Clean up test results directory
        if self.results_base.exists():
            shutil.rmtree(self.results_base)

    def test_path_helpers(self):
        """Verify that path helpers return correctly isolated paths."""
        res_dir = get_profile_results_dir(self.test_profile)
        self.assertTrue(str(res_dir).endswith(f"results/profiles/{self.test_profile}"))
        
        manifest_path = get_profile_manifest_path(self.test_profile)
        self.assertTrue(str(manifest_path).endswith(f"results/profiles/{self.test_profile}/manifests/experiment_manifest.json"))
        
        summary_path = get_profile_summary_path(self.test_profile)
        self.assertTrue(str(summary_path).endswith(f"results/profiles/{self.test_profile}/summaries/daily_summary.csv"))
        
        json_p, csv_p = resolve_daily_output_paths(self.test_profile, "replay_2026-03-22")
        self.assertTrue(str(json_p).endswith(f"results/profiles/{self.test_profile}/daily/replay_2026-03-22.json"))
        self.assertTrue(str(csv_p).endswith(f"results/profiles/{self.test_profile}/daily/replay_2026-03-22.csv"))

    def test_manifest_profile_metadata(self):
        """Verify that manifest includes the market_profile."""
        manifest_path = get_profile_manifest_path(self.test_profile)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        
        cfg_hash, cfg_dict = compute_config_hash(42, 10, market_profile=self.test_profile)
        write_manifest(manifest_path, cfg_hash, cfg_dict, "Test Label", market_profile=self.test_profile)
        
        with open(manifest_path, "r") as f:
            data = json.load(f)
            self.assertEqual(data["market_profile"], self.test_profile)
            self.assertEqual(data["config"]["market_profile"], self.test_profile)

    def test_profile_mismatch_safety(self):
        """Verify that check_manifest_and_warn raises SystemExit on profile mismatch."""
        manifest_path = get_profile_manifest_path(self.test_profile)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Create manifest with one profile
        cfg_hash, cfg_dict = compute_config_hash(42, 10, market_profile=self.test_profile)
        write_manifest(manifest_path, cfg_hash, cfg_dict, "Test Label", market_profile=self.test_profile)
        
        # Try to run with a DIFFERENT profile against the same manifest path
        with self.assertRaises(SystemExit):
             check_manifest_and_warn(cfg_hash, manifest_path, profile="wrong_profile")

if __name__ == "__main__":
    unittest.main()
