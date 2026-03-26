"""
bot/execution/assessor.py
Phase 12.2 — Execution quality assessor.

Evaluates four market-microstructure conditions against config thresholds
and produces an `ExecutionAssessment` with:
  - approved: bool
  - rejection_reasons: list of human-readable strings
  - tradability_score: float 0.0–1.0
  - spread_label, liquidity_label, staleness_label, expiry_label

DESIGN PRINCIPLE:
  ExecutionAssessor is a PURE evaluator — it does NOT gate trading.
  The risk manager still decides whether to trade.
  exec_approved is logged for research/analysis; live gating on execution
  quality is Phase 12.3+.
"""
from __future__ import annotations
from bot.execution.types import ExecutionAssessment, SignalFeatures


# ─────────────────────────────────────────────────────────────────────────────
# Label thresholds (relative to config values)
# ─────────────────────────────────────────────────────────────────────────────

# Spread labels: proportion of max_spread
_SPREAD_TIGHT_RATIO  = 0.5   # < 50% of max_spread → tight
# wide: 50–100% of max_spread; very_wide: >= max_spread

# Depth labels: multiples of min_depth_usd
_DEPTH_DEEP_MULTIPLE  = 2.0   # >= 2× min_depth → deep
# thin: >= 1×; very_thin: < 1×

# Expiry labels: multiples of min_time_to_close_mins
_EXPIRY_PLENTY_MULT  = 5.0   # >= 5× min_time → plenty
# near: >= 1×; critical: < 1×


# ─────────────────────────────────────────────────────────────────────────────
# Tradability score component weights
# ─────────────────────────────────────────────────────────────────────────────

_W_SPREAD   = 0.35   # spread matters most for fill quality
_W_DEPTH    = 0.30   # depth determines whether the order can be placed
_W_FRESHNESS = 0.20  # staleness impacts signal relevance
_W_EXPIRY   = 0.15   # expiry rarely binding but important when it is


class ExecutionAssessor:
    """
    Stateless execution quality evaluator.

    Usage:
        assessor = ExecutionAssessor()
        assessment = assessor.assess(features, settings)

    All threshold parameters are read from `settings` so the assessor
    automatically respects config overrides.
    """

    def assess(self, features: SignalFeatures, settings) -> ExecutionAssessment:
        """
        Evaluate microstructure conditions and return an ExecutionAssessment.

        Args:
            features:  SignalFeatures built from the current snapshot.
            settings:  bot.core.config.Settings (or any obj with the same attrs).

        Returns:
            ExecutionAssessment populated with all fields.
        """
        rejection_reasons: list[str] = []
        component_scores: dict[str, float] = {}

        # ── 1. Spread check ───────────────────────────────────────────────────
        spread = features.spread
        max_spread: float = settings.max_spread

        if spread >= max_spread:
            spread_ok = False
            rejection_reasons.append(f"spread_too_wide({spread:.4f})")
        else:
            spread_ok = True

        tight_threshold = max_spread * _SPREAD_TIGHT_RATIO
        if spread < tight_threshold:
            spread_label = "tight"
        elif spread < max_spread:
            spread_label = "wide"
        else:
            spread_label = "very_wide"

        component_scores["spread"] = 1.0 if spread_ok else 0.0

        # ── 2. Depth check ────────────────────────────────────────────────────
        total_depth = features.total_depth_usd
        min_depth: float = settings.min_depth_usd

        if total_depth < min_depth:
            depth_ok = False
            rejection_reasons.append(f"depth_too_thin({total_depth:.1f})")
        else:
            depth_ok = True

        deep_threshold = min_depth * _DEPTH_DEEP_MULTIPLE
        if total_depth >= deep_threshold:
            liquidity_label = "deep"
        elif total_depth >= min_depth:
            liquidity_label = "thin"
        else:
            liquidity_label = "very_thin"

        component_scores["depth"] = 1.0 if depth_ok else 0.0

        # ── 3. Staleness check ────────────────────────────────────────────────
        age_secs = features.snapshot_age_seconds
        max_age: int = settings.signal_staleness_seconds

        if age_secs > max_age:
            fresh_ok = False
            rejection_reasons.append(f"snapshot_stale({age_secs:.1f}s)")
        else:
            fresh_ok = True

        staleness_label = "fresh" if fresh_ok else "stale"
        component_scores["freshness"] = 1.0 if fresh_ok else 0.0

        # ── 4. Expiry check ───────────────────────────────────────────────────
        mins_left = features.minutes_to_expiry
        min_mins: float = settings.min_time_to_close_mins

        if mins_left < min_mins:
            expiry_ok = False
            rejection_reasons.append(f"expiry_too_close({mins_left:.1f}m)")
        else:
            expiry_ok = True

        plenty_threshold = min_mins * _EXPIRY_PLENTY_MULT
        if mins_left >= plenty_threshold:
            expiry_label = "plenty"
        elif mins_left >= min_mins:
            expiry_label = "near"
        else:
            expiry_label = "critical"

        component_scores["expiry"] = 1.0 if expiry_ok else 0.0

        # ── Tradability score ─────────────────────────────────────────────────
        tradability_score = round(
            component_scores["spread"]    * _W_SPREAD   +
            component_scores["depth"]     * _W_DEPTH    +
            component_scores["freshness"] * _W_FRESHNESS +
            component_scores["expiry"]    * _W_EXPIRY,
            4,
        )

        return ExecutionAssessment(
            signal_id=features.market_id,   # best available ID at this point
            approved=len(rejection_reasons) == 0,
            rejection_reasons=rejection_reasons,
            tradability_score=tradability_score,
            spread_label=spread_label,
            liquidity_label=liquidity_label,
            staleness_label=staleness_label,
            expiry_label=expiry_label,
        )
