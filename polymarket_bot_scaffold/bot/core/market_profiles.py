from __future__ import annotations
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

@dataclass
class MatchResult:
    matched: bool
    reasons_passed: list[str] = field(default_factory=list)
    reasons_failed: list[str] = field(default_factory=list)
    detected_asset: str | None = None
    detected_horizon_minutes: int | None = None
    detected_directional_terms: list[str] = field(default_factory=list)
    detected_binary: bool | None = None

@dataclass
class MarketProfile:
    name: str
    description: str
    asset_keywords: list[str]
    horizon_minutes: int | None = None
    require_directional: bool = True
    allowed_direction_terms: list[str] = field(default_factory=list)
    exclude_keywords: list[str] = field(default_factory=list)
    require_binary: bool = True
    preferred_categories: list[str] | None = None
    slug_hints: list[str] = field(default_factory=list)
    question_hints: list[str] = field(default_factory=list)
    allow_time_interval_parsing: bool = True

class HorizonParser:
    @staticmethod
    def parse(text: str, slug: str = "") -> int | None:
        text_lower = text.lower()
        slug_lower = slug.lower()
        
        # 1. Direct tokens
        if "15m" in text_lower or "15 min" in text_lower or "15-min" in text_lower or "15 minute" in text_lower:
            return 15
        if "1h" in text_lower or "1 hour" in text_lower or "60 min" in text_lower:
            return 60
        if "daily" in text_lower or "day" in text_lower:
            return 1440
            
        # 2. Timestamp intervals: "7:15AM-7:30AM" or "1:00PM and 2:00PM"
        # Matches patterns like 7:15AM-7:30AM, 10:30PM-11:00PM, 12:00AM - 1:00AM, 1:00PM and 2:00PM
        interval_regex = r"(\d{1,2}:\d{2})(AM|PM)\s*(?:-|\band\b)\s*(\d{1,2}:\d{2})(AM|PM)"
        match = re.search(interval_regex, text, re.IGNORECASE)
        if match:
            t1_str, p1, t2_str, p2 = match.groups()
            try:
                fmt = "%I:%M%p"
                t1 = datetime.strptime(f"{t1_str}{p1.upper()}", fmt)
                t2 = datetime.strptime(f"{t2_str}{p2.upper()}", fmt)
                diff = (t2 - t1).total_seconds() / 60
                if diff < 0: # Crossed midnight, e.g. 11:45PM-12:00AM
                    diff += 1440
                return int(diff)
            except ValueError:
                pass
                
        # 3. Slug hints
        if "15m" in slug_lower: return 15
        if "1h" in slug_lower: return 60
        
        return None

class ProfileMatcher:
    def __init__(self, profile: MarketProfile):
        self.profile = profile

    def matches(self, market: dict[str, Any], explain: bool = False) -> MatchResult | bool:
        res = MatchResult(matched=True)
        q = market.get("question", "").lower()
        s = market.get("slug", "").lower()
        
        # 1. Asset Match
        asset_found = False
        for ack in self.profile.asset_keywords:
            if ack.lower() in q or ack.lower() in s:
                asset_found = True
                res.detected_asset = ack
                res.reasons_passed.append(f"Asset keyword '{ack}' found")
                break
        if not asset_found:
            res.matched = False
            res.reasons_failed.append(f"No asset keywords {self.profile.asset_keywords} found in title or slug")

        # 2. Horizon Match
        detected_horizon = HorizonParser.parse(market.get("question", ""), s)
        res.detected_horizon_minutes = detected_horizon
        if self.profile.horizon_minutes is not None:
            if detected_horizon != self.profile.horizon_minutes:
                res.matched = False
                res.reasons_failed.append(f"Horizon mismatch: expected {self.profile.horizon_minutes}m, detected {detected_horizon}m")
            else:
                res.reasons_passed.append(f"Horizon matched {detected_horizon}m")

        # 3. Directional Match
        if self.profile.require_directional:
            dir_terms = self.profile.allowed_direction_terms or ["up", "down", "above", "below"]
            found_terms = [t for t in dir_terms if t.lower() in q or (t.lower() + "down" in s if t.lower() == "up" else False)]
            # Note: handle 'updown' slug edge case
            if "updown" in s:
                if "up" not in found_terms: found_terms.append("up")
                if "down" not in found_terms: found_terms.append("down")
                
            res.detected_directional_terms = found_terms
            if not found_terms:
                res.matched = False
                res.reasons_failed.append(f"No directional terms {dir_terms} found")
            else:
                res.reasons_passed.append(f"Directional terms found: {found_terms}")

        # 4. Binary Match
        tokens = market.get("tokens", [])
        is_binary = len(tokens) == 2
        res.detected_binary = is_binary
        if self.profile.require_binary and not is_binary:
            res.matched = False
            res.reasons_failed.append(f"Expected 2 outcomes (binary), found {len(tokens)}")
        elif self.profile.require_binary:
             res.reasons_passed.append("Binary outcome check passed")

        # 5. Exclusions
        for ex in self.profile.exclude_keywords:
            if ex.lower() in q or ex.lower() in s:
                res.matched = False
                res.reasons_failed.append(f"Exclusion keyword '{ex}' found")

        if explain:
            return res
        return res.matched

# --- Registry ---

DEFAULT_DIRECTION_TERMS = ["up", "down", "above", "below"]

MARKET_PROFILES: dict[str, MarketProfile] = {
    "eth_15m_direction": MarketProfile(
        name="eth_15m_direction",
        description="ETH 15-minute directional markets (Up/Down/Above/Below)",
        asset_keywords=["eth", "ethereum"],
        horizon_minutes=15,
        allowed_direction_terms=DEFAULT_DIRECTION_TERMS,
    ),
    "btc_15m_direction": MarketProfile(
        name="btc_15m_direction",
        description="BTC 15-minute directional markets (Up/Down/Above/Below)",
        asset_keywords=["btc", "bitcoin"],
        horizon_minutes=15,
        allowed_direction_terms=DEFAULT_DIRECTION_TERMS,
    ),
    "btc_1h_direction": MarketProfile(
        name="btc_1h_direction",
        description="BTC 1-hour directional markets",
        asset_keywords=["btc", "bitcoin"],
        horizon_minutes=60,
        allowed_direction_terms=DEFAULT_DIRECTION_TERMS,
    ),
    "eth_daily_direction": MarketProfile(
        name="eth_daily_direction",
        description="ETH daily directional markets",
        asset_keywords=["eth", "ethereum"],
        horizon_minutes=1440,
        allowed_direction_terms=DEFAULT_DIRECTION_TERMS,
    ),
    "generic_binary_high_liquidity": MarketProfile(
        name="generic_binary_high_liquidity",
        description="Any high-liquidity binary market (less restrictive)",
        asset_keywords=[], # Empty means skip asset check if logic allows, or add common ones
        require_directional=False,
        require_binary=True,
    ),
}

def get_profile(name: str) -> MarketProfile:
    if name not in MARKET_PROFILES:
        raise ValueError(f"Unknown market profile: {name}")
    return MARKET_PROFILES[name]
