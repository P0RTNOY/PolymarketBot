def compute_hit_rate(wins: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return wins / total
