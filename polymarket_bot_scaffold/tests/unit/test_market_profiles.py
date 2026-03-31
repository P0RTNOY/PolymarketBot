import unittest
from bot.core.market_profiles import MarketProfile, ProfileMatcher, HorizonParser, get_profile

class TestMarketProfiles(unittest.TestCase):
    def test_horizon_parser_tokens(self):
        self.assertEqual(HorizonParser.parse("Predict ETH (15m)"), 15)
        self.assertEqual(HorizonParser.parse("Daily Price Move"), 1440)
        self.assertEqual(HorizonParser.parse("Something 1h"), 60)
        
    def test_horizon_parser_interval(self):
        # 7:15AM-7:30AM = 15m
        self.assertEqual(HorizonParser.parse("ETH moves up (7:15AM-7:30AM)"), 15)
        # 10:30PM-11:30PM = 60m
        self.assertEqual(HorizonParser.parse("BTC moves down (10:30PM-11:30PM)"), 60)
        # 11:45PM-12:00AM = 15m
        self.assertEqual(HorizonParser.parse("ETH (11:45PM-12:00AM)"), 15)

    def test_horizon_parser_slug(self):
        self.assertEqual(HorizonParser.parse("Garbage Question", "eth-price-15m-updown"), 15)

    def test_eth_15m_profile_match(self):
        profile = get_profile("eth_15m_direction")
        matcher = ProfileMatcher(profile)
        
        # Valid ETH 15m directional
        m1 = {
            "question": "Will Ethereum move up (7:15AM-7:30AM)?",
            "slug": "eth-updown-15m",
            "tokens": [{"token_id": "1"}, {"token_id": "2"}]
        }
        res = matcher.matches(m1, explain=True)
        self.assertTrue(res.matched)
        self.assertEqual(res.detected_asset, "eth")
        self.assertEqual(res.detected_horizon_minutes, 15)
        
    def test_btc_1h_profile_match(self):
        profile = get_profile("btc_1h_direction")
        matcher = ProfileMatcher(profile)
        
        m1 = {
            "question": "Will BTC move ABOVE 60000 between 1:00PM and 2:00PM?",
            "slug": "btc-60000-above",
            "tokens": [{"token_id": "1"}, {"token_id": "2"}]
        }
        res = matcher.matches(m1, explain=True)
        self.assertTrue(res.matched)
        self.assertEqual(res.detected_horizon_minutes, 60)

    def test_failure_cases(self):
        profile = get_profile("eth_15m_direction")
        matcher = ProfileMatcher(profile)
        
        # Wrong asset
        m1 = {"question": "Will BTC move up?", "slug": "btc-up", "tokens": [{}, {}]}
        self.assertFalse(matcher.matches(m1))
        
        # Wrong horizon
        m2 = {"question": "Will ETH move up (Daily)?", "slug": "eth-daily", "tokens": [{}, {}]}
        self.assertFalse(matcher.matches(m2))
        
        # Not binary
        m3 = {
            "question": "Will ETH move up (15m)?", 
            "slug": "eth-15m", 
            "tokens": [{}, {}, {}] # 3 tokens
        }
        res = matcher.matches(m3, explain=True)
        self.assertFalse(res.matched)
        self.assertIn("Expected 2 outcomes", res.reasons_failed[0])

if __name__ == "__main__":
    unittest.main()
