"""
bot/analytics/candidate_buckets.py
Phase 12.1 — Edge bucket classifier for shadow candidate logging.

Pure functions, no I/O, no DB access.  Import freely.

CANDIDATE_FLOOR: the minimum abs(edge) we bother logging at all.
  - Below this the opportunity is too weak to be research-useful.
  - Does NOT affect the min_edge gate for actual trading.

EDGE_BUCKETS: ordered list of (label, upper_bound) used to classify candidates.
  - Sentinel bucket "0.04+" has no upper bound (float('inf')).
"""
from __future__ import annotations

# Minimum abs(edge) worth shadow-logging.
# Below this floor we skip the candidate entirely (noise / rounding).
CANDIDATE_FLOOR: float = 0.005

# Status labels stored in SignalRecord.candidate_status
CANDIDATE  = "CANDIDATE"    # above floor, below min_edge  → shadow log only
TRADEABLE  = "TRADEABLE"    # above min_edge                → entered trade flow
REJECTED_EXEC = "REJECTED_EXEC"  # reserved for Phase 12.2
REJECTED_RISK = "REJECTED_RISK"  # reserved for Phase 12.2

# Ordered bucket definitions: (label, lower_inclusive, upper_exclusive)
# The last bucket has no upper bound.
EDGE_BUCKET_DEFS: list[tuple[str, float, float]] = [
    ("0.00-0.01", 0.000, 0.010),
    ("0.01-0.02", 0.010, 0.020),
    ("0.02-0.03", 0.020, 0.030),
    ("0.03-0.04", 0.030, 0.040),
    ("0.04+",     0.040, float("inf")),
]

# Convenience list of bucket labels in order (useful for report column ordering)
EDGE_BUCKET_LABELS: list[str] = [b[0] for b in EDGE_BUCKET_DEFS]


def edge_to_bucket(abs_edge: float) -> str:
    """
    Map an absolute edge value to its bucket label.

    Args:
        abs_edge: abs(model_prob - market_prob).  Must be >= 0.

    Returns:
        One of the labels in EDGE_BUCKET_LABELS, or "below_floor" if
        abs_edge < CANDIDATE_FLOOR.

    Examples:
        >>> edge_to_bucket(0.000)
        'below_floor'
        >>> edge_to_bucket(0.005)
        '0.00-0.01'
        >>> edge_to_bucket(0.010)
        '0.01-0.02'
        >>> edge_to_bucket(0.035)
        '0.03-0.04'
        >>> edge_to_bucket(0.07)
        '0.04+'
    """
    if abs_edge < CANDIDATE_FLOOR:
        return "below_floor"
    for label, lo, hi in EDGE_BUCKET_DEFS:
        if lo <= abs_edge < hi:
            return label
    # Shouldn't reach here since last bucket is +inf, but be safe
    return "0.04+"


def candidate_status_for_edge(abs_edge: float, min_edge: float) -> str:
    """
    Return the candidate status string for a given edge magnitude.

    Args:
        abs_edge:  abs(model_prob - market_prob)
        min_edge:  the configured trading threshold (e.g. 0.04)

    Returns:
        TRADEABLE if abs_edge >= min_edge, else CANDIDATE.
        Returns empty string "" if abs_edge < CANDIDATE_FLOOR (should not log).
    """
    if abs_edge < CANDIDATE_FLOOR:
        return ""
    if abs_edge >= min_edge:
        return TRADEABLE
    return CANDIDATE


def is_loggable(abs_edge: float) -> bool:
    """Return True if this candidate is above the floor and worth logging."""
    return abs_edge >= CANDIDATE_FLOOR
