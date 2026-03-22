"""
Rolling daily summary writer for multi-day experiment tracking.

Appends one row per (date, strategy_version) to results/summaries/daily_summary.csv.
Designed to accumulate across many days without overwriting.
"""
import csv
import json
import os
import statistics
from datetime import date
from pathlib import Path

SUMMARY_PATH = Path("results/summaries/daily_summary.csv")

FIELDNAMES = [
    "date",
    "strategy_version",
    "runs",
    "base_seed",
    "signals_generated",
    "approved_count",
    "orders_placed",
    "filled_count",
    "fill_rate_pct",
    "win_rate_pct",
    "trades_count",
    "mean_pnl",
    "median_pnl",
    "best_pnl",
    "worst_pnl",
    "pnl_stdev",
    "average_fill_delay_secs",
    "settlement_mode",
    "config_hash",
    "config_label",
]


def _compute_mc_stats(mc_pnl_list: list[float]) -> dict:
    if not mc_pnl_list:
        return {"mean_pnl": 0.0, "median_pnl": 0.0, "best_pnl": 0.0,
                "worst_pnl": 0.0, "pnl_stdev": 0.0}
    return {
        "mean_pnl":   round(statistics.mean(mc_pnl_list), 6),
        "median_pnl": round(statistics.median(mc_pnl_list), 6),
        "best_pnl":   round(max(mc_pnl_list), 6),
        "worst_pnl":  round(min(mc_pnl_list), 6),
        "pnl_stdev":  round(statistics.stdev(mc_pnl_list) if len(mc_pnl_list) > 1 else 0.0, 6),
    }


def _pct(num: int, den: int) -> float:
    return round(100 * num / max(1, den), 2)


def append_daily_rows(
    replay_date: date,
    mc_pnl: dict[str, list[float]],
    last_run_stats: dict[str, dict],
    runs: int,
    seed: int | None,
    settlement_mode: str,
    config_hash: str,
    config_label: str,
    summary_path: Path = SUMMARY_PATH,
) -> None:
    summary_path.parent.mkdir(parents=True, exist_ok=True)

    write_header = not summary_path.exists()

    with open(summary_path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        if write_header:
            writer.writeheader()

        for strategy_name, st in last_run_stats.items():
            pnl_list = mc_pnl.get(strategy_name, [])
            mc_stats = _compute_mc_stats(pnl_list)
            delays = st.get("fill_delays", [])
            avg_delay = round(sum(delays) / max(1, len(delays)), 2)

            # trades_count = number of trades evaluated across all runs
            # (we only have last-run stats for granular data; mc captures PnL distribution)
            row = {
                "date":                  replay_date.isoformat(),
                "strategy_version":      strategy_name,
                "runs":                  runs,
                "base_seed":             seed,
                "signals_generated":     st.get("signals", 0),
                "approved_count":        st.get("orders", 0),
                "orders_placed":         st.get("orders", 0),
                "filled_count":          st.get("filled", 0),
                "fill_rate_pct":         _pct(st.get("filled", 0), st.get("orders", 0)),
                "win_rate_pct":          _pct(st.get("wins", 0), st.get("filled", 0)),
                "trades_count":          len(pnl_list),
                "average_fill_delay_secs": avg_delay,
                "settlement_mode":       settlement_mode,
                "config_hash":           config_hash,
                "config_label":          config_label,
                **mc_stats,
            }
            writer.writerow(row)


def print_console_summary(
    replay_date: date,
    mc_pnl: dict[str, list[float]],
    last_run_stats: dict[str, dict],
    runs: int,
    seed: int | None,
    settlement_mode: str,
    config_hash: str,
) -> None:
    """Compact, readable daily console summary."""
    print(f"\n{'━'*65}")
    print(f"  📊 DAILY SUMMARY  {replay_date}  |  runs={runs}  seed={seed}")
    print(f"  settlement={settlement_mode}  config={config_hash}")
    print(f"{'━'*65}")
    print(f"  {'Strategy':<28} {'Mean':>8} {'Median':>8} {'Best':>8} {'Worst':>8} {'Stdev':>7}")
    print(f"  {'':─<60}")

    for sname, pnl_list in mc_pnl.items():
        label = "V1" if "v1" in sname else "V2"
        mc = _compute_mc_stats(pnl_list)
        st = last_run_stats.get(sname, {})
        fills = st.get("filled", 0)
        orders = st.get("orders", 0)
        wins = st.get("wins", 0)
        fill_rate = _pct(fills, orders)
        win_rate  = _pct(wins, fills)
        print(
            f"  {sname:<28}"
            f" {mc['mean_pnl']:>+8.4f}"
            f" {mc['median_pnl']:>+8.4f}"
            f" {mc['best_pnl']:>+8.4f}"
            f" {mc['worst_pnl']:>+8.4f}"
            f" {mc['pnl_stdev']:>7.4f}"
        )
        print(
            f"  {'':>28}"
            f"  fills={fills}/{orders} ({fill_rate}%)"
            f"  wins={wins} ({win_rate}%)"
        )

    print(f"{'━'*65}\n")
