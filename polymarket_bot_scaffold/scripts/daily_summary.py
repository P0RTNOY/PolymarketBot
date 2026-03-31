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
    "market_profile",
    "strategy_version",
    "experiment_label",
    "config_hash",
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
    # Phase 12.3B — Universe Quality
    "median_spread",
    "p90_spread",
    "pct_snapshots_under_max_spread",
    "median_total_depth_usd",
    "pct_snapshots_above_min_depth_usd",
    "pct_snapshots_meeting_exec_conditions",
    "candidate_to_tradeable_rate",
    "tradeable_to_exec_approved_rate",
    "dominant_exec_rejection_reason",
]


def _compute_mc_stats(mc_pnl_list: list[float]) -> dict:
    if not mc_pnl_list:
        return {"mean_pnl": 0.0, "median_pnl": 0.0, "best_pnl": 0.0,
                "worst_pnl": 0.0, "pnl_stdev": 0.0}
    return {
        "mean_pnl":   statistics.mean(mc_pnl_list),
        "median_pnl": statistics.median(mc_pnl_list),
        "best_pnl":   max(mc_pnl_list),
        "worst_pnl":  min(mc_pnl_list),
        "pnl_stdev":  statistics.stdev(mc_pnl_list) if len(mc_pnl_list) > 1 else 0.0,
    }


def _pct(num: int, den: int) -> str:
    return f"{100 * num / max(1, den):.2f}"


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
    universe_quality: dict[str, dict] | None = None,
    market_profile: str = "unknown", # Added market_profile to kwargs
) -> None:
    summary_path.parent.mkdir(parents=True, exist_ok=True)

    write_header = not summary_path.exists()
    date_str = replay_date.isoformat()
    # Get quality metrics for this specific day if available
    q = (universe_quality or {}).get(date_str, {})
    snap_q = q.get("snapshot_quality", {})
    funnel = q.get("opportunity_funnel", {})
    failures = q.get("failure_analysis", {})

    with open(summary_path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        if write_header:
            writer.writeheader()

        for strategy_name, st in last_run_stats.items():
            pnl_list = mc_pnl.get(strategy_name, [])
            mc_stats = _compute_mc_stats(pnl_list)
            # Format mc_stats for CSV (high precision)
            mc_formatted = {k: f"{v:.6f}" for k, v in mc_stats.items()}
            delays = st.get("fill_delays", [])
            avg_delay = f"{statistics.mean(delays):.2f}" if delays else "0.00"

            row = {
                "date":                  date_str,
                "market_profile":        market_profile,
                "strategy_version":      strategy_name,
                "experiment_label":      config_label,
                "config_hash":           config_hash,
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
                # Universe Quality Fields
                "median_spread":         snap_q.get("median_spread", 0.0),
                "p90_spread":            snap_q.get("p90_spread", 0.0),
                "pct_snapshots_under_max_spread": snap_q.get("pct_snapshots_under_max_spread", 0.0),
                "median_total_depth_usd": snap_q.get("median_total_depth_usd", 0.0),
                "pct_snapshots_above_min_depth_usd": snap_q.get("pct_snapshots_above_min_depth_usd", 0.0),
                "pct_snapshots_meeting_exec_conditions": snap_q.get("pct_snapshots_meeting_exec_conditions", 0.0),
                "candidate_to_tradeable_rate": funnel.get("candidate_to_tradeable_rate", 0.0),
                "tradeable_to_exec_approved_rate": funnel.get("tradeable_to_exec_approved_rate", 0.0),
                "dominant_exec_rejection_reason": failures.get("dominant_exec_rejection_reason", "none"),
                **mc_formatted,
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
    universe_quality: dict[str, dict] | None = None,
    market_profile: str = "unknown",
    config_label: str = "unknown",
) -> None:
    """Compact, readable daily console summary."""
    print(f"\n{'━'*65}")
    print(f"  📊 DAILY SUMMARY  {market_profile.upper()}  |  {replay_date}")
    print(f"  runs={runs}  seed={seed}  config={config_hash}")
    print(f"  label={config_label}  settlement={settlement_mode}")
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

    # Universe Quality Block
    if universe_quality:
        date_str = replay_date.isoformat()
        q = (universe_quality or {}).get(date_str, {})
        snap_q = q.get("snapshot_quality", {})
        funnel = q.get("opportunity_funnel", {})
        verdict = q.get("universe_verdict", {})
        
        if q:
            print(f"\n  🌐 UNIVERSE QUALITY ({date_str})")
            print(f"  {'Status':<15}: {verdict.get('universe_status', 'N/A').upper()}")
            print(f"  {'Bottleneck':<15}: {verdict.get('primary_bottleneck', 'N/A')}")
            
            print(f"\n  Market Health:")
            print(f"    - Median Spread : {snap_q.get('median_spread', 0.0):.4f}  (P90: {snap_q.get('p90_spread', 0.0):.4f})")
            print(f"    - Median Depth  : ${snap_q.get('median_total_depth_usd', 0.0):,.0f} (P10: ${snap_q.get('p10_total_depth_usd', 0.0):,.0f})")
            print(f"    - Exec OK Rate  : {snap_q.get('pct_snapshots_meeting_exec_conditions', 0.0)*100:.1f}%")
            
            print(f"\n  Funnel Efficiency:")
            print(f"    - Candidate -> Tradeable : {funnel.get('candidate_to_tradeable_rate', 0.0)*100:.1f}%")
            print(f"    - Tradeable -> Exec OK   : {funnel.get('tradeable_to_exec_approved_rate', 0.0)*100:.1f}%")
            
            if verdict.get("recommended_action"):
                print(f"\n  👉 {verdict.get('recommended_action').replace('_', ' ').capitalize()}")

    print(f"{'━'*65}\n")
