#!/usr/bin/env python3
"""
Deterministic paper-trading replay engine (v2).

Usage:
    # Single day
    python scripts/replay_paper_day.py --date 2026-03-21

    # Date range
    python scripts/replay_paper_day.py --start 2026-03-18 --end 2026-03-22

    # Reproducible single run
    python scripts/replay_paper_day.py --date 2026-03-21 --seed 42

    # Monte Carlo: 20 runs, report mean/median/worst/best
    python scripts/replay_paper_day.py --date 2026-03-21 --runs 20 --seed 42

    # Export results
    python scripts/replay_paper_day.py --date 2026-03-21 --out results/replay_20260321.json

    # Both
    python scripts/replay_paper_day.py --start 2026-03-18 --end 2026-03-22 --runs 10 --seed 42 --out results/range.json

Settlement priority
    1. If the market is RESOLVED in your DB → use winning_token_id for $1/$0 final outcome
    2. Otherwise → fall back to final recorded midpoint (Layer A approximation)
"""
import sys
import os
import argparse
import json
import csv
import random
import statistics
from datetime import datetime, timezone, timedelta
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bot.data.repositories.snapshots import SnapshotRepository
from bot.data.session import SessionLocal
from bot.data.models import Market
from bot.execution.types import MarketSnapshot as SnapshotPydantic, TradeSignal
from bot.core.config import get_settings
from bot.strategies.eth_direction_15m import ETHDirection15mStrategy
from bot.strategies.eth_direction_15m_v2 import ETHDirection15mV2Strategy
from bot.analytics.candidate_buckets import TRADEABLE, edge_to_bucket
from sqlalchemy import select

STRATEGIES = [ETHDirection15mStrategy(), ETHDirection15mV2Strategy()]
FILL_LOOKAHEAD = 5


# ─────────────────────────────────────────────────────────────────────────────
# Data helpers
# ─────────────────────────────────────────────────────────────────────────────

def db_row_to_pydantic(row) -> SnapshotPydantic:
    ts = row.timestamp
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return SnapshotPydantic(
        market_id=row.market_id,
        token_id=row.token_id,
        question=row.market_id,
        best_bid=row.best_bid,
        best_ask=row.best_ask,
        midpoint=row.midpoint,
        spread=row.spread,
        bid_depth_usd=row.bid_depth_usd,
        ask_depth_usd=row.ask_depth_usd,
        timestamp=ts,
        end_time=None,
    )


def load_market_resolutions() -> dict[str, str | None]:
    """Map market_id → winning_token_id (None if unresolved)."""
    with SessionLocal() as session:
        markets = session.scalars(select(Market)).all()
        return {m.id: m.winning_token_id for m in markets}


# ─────────────────────────────────────────────────────────────────────────────
# Fill emulator
# ─────────────────────────────────────────────────────────────────────────────

def try_simulate_fill(
    order_price: float,
    side: str,
    future_snaps: list,
    rng: random.Random,
    passive_fill_prob: float,
) -> tuple[bool, float, float]:
    """Returns (filled, fill_price, delay_secs)."""
    for snap in future_snaps[:FILL_LOOKAHEAD]:
        touched = (
            (side == "BUY_YES" and snap.best_bid >= order_price) or
            (side == "BUY_NO"  and snap.best_ask <= order_price)
        )
        if touched:
            if rng.random() < passive_fill_prob:
                delay = (snap.timestamp - future_snaps[0].timestamp).total_seconds()
                return True, order_price, delay
            return False, 0.0, 0.0
    return False, 0.0, 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Settlement
# ─────────────────────────────────────────────────────────────────────────────

def compute_settlement_value(
    side: str,
    token_id: str,
    market_id: str,
    final_snap: SnapshotPydantic,
    resolutions: dict[str, str | None],
) -> tuple[float, str]:
    """
    Returns (settlement_value_per_share, exit_method).
    exit_method: 'true_resolution' | 'midpoint_fallback'
    """
    winning_token = resolutions.get(market_id)
    if winning_token is not None:
        # True binary settlement: token either worth $1 or $0
        if side == "BUY_YES":
            val = 1.0 if token_id == winning_token else 0.0
        else:
            # BUY_NO: we hold the complement token
            val = 0.0 if token_id == winning_token else 1.0
        return val, "true_resolution"
    else:
        # Fallback: use final midpoint as estimated value
        val = final_snap.midpoint if side == "BUY_YES" else (1.0 - final_snap.midpoint)
        return val, "midpoint_fallback"


# ─────────────────────────────────────────────────────────────────────────────
# Per-strategy state factory
# ─────────────────────────────────────────────────────────────────────────────

def fresh_state() -> dict:
    return {
        "signals": 0,
        "rejected_risk": 0,
        "orders": 0,
        "filled": 0,
        "wins": 0,
        "losses": 0,
        "realized_pnl": 0.0,
        "fill_delays": [],
        "reject_reasons": defaultdict(int),
        "pnl_by_hour": defaultdict(float),
        "pnl_by_edge_bucket": {"0.00-0.02": 0.0, "0.02-0.05": 0.0, "0.05+": 0.0},
        "pnl_by_spread_bucket": {"0.00-0.02": 0.0, "0.02-0.05": 0.0, "0.05+": 0.0},
        "best_trade": None,
        "worst_trade": None,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Core single-run replay
# ─────────────────────────────────────────────────────────────────────────────

def run_single(
    token_rows: dict[str, list],
    resolutions: dict[str, str | None],
    rng: random.Random,
    passive_fill_prob: float = 0.30,
) -> tuple[dict[str, dict], list[dict]]:
    """
    Returns (per_strategy_stats, trades).
    trades is a list of audit-row dicts, one per signal evaluated.
    """
    from bot.risk.manager import RiskManager
    settings = get_settings()
    risk_mgr = RiskManager()
    per_strategy = {s.name: fresh_state() for s in STRATEGIES}
    trades: list[dict] = []

    for token_id, rows in token_rows.items():
        snaps = [db_row_to_pydantic(r) for r in rows]

        for i, current in enumerate(snaps):
            previous = snaps[i - 1] if i > 0 else None

            for strategy in STRATEGIES:
                st = per_strategy[strategy.name]
                signal: TradeSignal | None = strategy.evaluate(current, previous)

                audit_row: dict = {
                    "timestamp": current.timestamp.isoformat(),
                    "market_id": current.market_id,
                    "token_id": token_id,
                    "strategy_version": strategy.name,
                    "signal_edge": None,
                    "approved": False,
                    "rejection_reason": None,
                    "order_placed": False,
                    "filled": False,
                    "fill_delay_secs": None,
                    "exit_method": None,
                    "realized_pnl": None,
                    # Phase 12.1
                    "candidate_status": TRADEABLE if signal is not None else None,
                    "edge_bucket": edge_to_bucket(abs(signal.edge)) if signal is not None else None,
                }

                if signal is None:
                    trades.append(audit_row)
                    continue

                st["signals"] += 1
                audit_row["signal_edge"] = round(signal.edge, 5)

                # Risk evaluation
                risk_ctx = {
                    "now": current.timestamp,
                    "daily_pnl": st["realized_pnl"],
                    "consecutive_losses": 0,
                    "last_loss_time": None,
                    "open_count": st["orders"] - st["filled"],
                    "notional_usd": (st["orders"] - st["filled"]) * settings.max_order_usd,
                    "open_positions": [],
                }
                sig_proxy = type("S", (), {
                    "market_id": signal.market_id,
                    "token_id": signal.token_id,
                    "side": signal.side,
                    "edge": signal.edge,
                    "suggested_size_usd": signal.suggested_size_usd,
                    "spread_at_entry": current.spread,
                    "time_remaining_at_entry": 15.0,
                })()

                approved, reason = risk_mgr.approve(sig_proxy, risk_ctx)
                audit_row["approved"] = approved

                if not approved:
                    st["rejected_risk"] += 1
                    base = reason.split("(")[0]
                    st["reject_reasons"][base] += 1
                    audit_row["rejection_reason"] = base
                    trades.append(audit_row)
                    continue

                st["orders"] += 1
                audit_row["order_placed"] = True
                future_snaps = snaps[i + 1:]

                filled, fill_price, delay = try_simulate_fill(
                    signal.suggested_price, signal.side, future_snaps, rng, passive_fill_prob
                )

                if not filled:
                    trades.append(audit_row)
                    continue

                st["filled"] += 1
                audit_row["filled"] = True
                audit_row["fill_delay_secs"] = round(delay, 1)
                st["fill_delays"].append(delay)

                final_snap = snaps[-1]
                outcome_val, exit_method = compute_settlement_value(
                    signal.side, token_id, current.market_id, final_snap, resolutions
                )
                audit_row["exit_method"] = exit_method

                pnl = (outcome_val - fill_price) * (signal.suggested_size_usd / max(fill_price, 0.01))
                pnl = round(pnl, 4)
                st["realized_pnl"] += pnl
                audit_row["realized_pnl"] = pnl

                if pnl > 0:
                    st["wins"] += 1
                else:
                    st["losses"] += 1

                if st["best_trade"] is None or pnl > st["best_trade"]:
                    st["best_trade"] = pnl
                if st["worst_trade"] is None or pnl < st["worst_trade"]:
                    st["worst_trade"] = pnl

                hour = current.timestamp.strftime("%H:00")
                st["pnl_by_hour"][hour] += pnl

                edge_abs = abs(signal.edge)
                if edge_abs < 0.02:
                    st["pnl_by_edge_bucket"]["0.00-0.02"] += pnl
                elif edge_abs < 0.05:
                    st["pnl_by_edge_bucket"]["0.02-0.05"] += pnl
                else:
                    st["pnl_by_edge_bucket"]["0.05+"] += pnl

                sp = current.spread
                if sp < 0.02:
                    st["pnl_by_spread_bucket"]["0.00-0.02"] += pnl
                elif sp < 0.05:
                    st["pnl_by_spread_bucket"]["0.02-0.05"] += pnl
                else:
                    st["pnl_by_spread_bucket"]["0.05+"] += pnl

                trades.append(audit_row)

    return per_strategy, trades


# ─────────────────────────────────────────────────────────────────────────────
# Report printer
# ─────────────────────────────────────────────────────────────────────────────

def print_report(
    per_strategy: dict[str, dict],
    monte_carlo: dict[str, list[float]] | None = None,
) -> None:
    v1 = per_strategy.get("eth_direction_15m_v1", fresh_state())
    v2 = per_strategy.get("eth_direction_15m_v2", fresh_state())

    print(f"\n{'─'*70}")
    print(f"{'METRIC':<35}{'V1':>16}{'V2':>16}")
    print(f"{'─'*70}")

    def pct(num, den): return f"{100*num/max(1,den):.1f}%"
    def fmt(v, f="{:.4f}"): return f.format(v) if v is not None else "N/A"

    print(f"{'Signals generated':<35}{v1['signals']:>16}{v2['signals']:>16}")
    print(f"{'Rejected by risk mgr':<35}{v1['rejected_risk']:>16}{v2['rejected_risk']:>16}")
    print(f"{'Orders placed':<35}{v1['orders']:>16}{v2['orders']:>16}")
    print(f"{'Filled':<35}{v1['filled']:>16}{v2['filled']:>16}")
    print(f"{'Fill rate':<35}{pct(v1['filled'],v1['orders']):>16}{pct(v2['filled'],v2['orders']):>16}")
    print(f"{'Win rate':<35}{pct(v1['wins'],v1['filled']):>16}{pct(v2['wins'],v2['filled']):>16}")
    print(f"{'Realized PnL ($)':<35}{v1['realized_pnl']:>16.4f}{v2['realized_pnl']:>16.4f}")
    print(f"{'Best trade ($)':<35}{fmt(v1['best_trade']):>16}{fmt(v2['best_trade']):>16}")
    print(f"{'Worst trade ($)':<35}{fmt(v1['worst_trade']):>16}{fmt(v2['worst_trade']):>16}")
    d1 = sum(v1['fill_delays'])/max(1, len(v1['fill_delays']))
    d2 = sum(v2['fill_delays'])/max(1, len(v2['fill_delays']))
    print(f"{'Avg fill delay (s)':<35}{d1:>16.1f}{d2:>16.1f}")

    # Monte Carlo summary
    if monte_carlo:
        print(f"\n{'─'*70}")
        print("Monte Carlo PnL distribution (across all runs)")
        for sname, pnl_list in monte_carlo.items():
            label = "V1" if "v1" in sname else "V2"
            if not pnl_list:
                continue
            print(f"  {label}: mean={statistics.mean(pnl_list):+.4f}  "
                  f"median={statistics.median(pnl_list):+.4f}  "
                  f"best={max(pnl_list):+.4f}  "
                  f"worst={min(pnl_list):+.4f}  "
                  f"stdev={statistics.stdev(pnl_list) if len(pnl_list) > 1 else 0:.4f}")

    print(f"\n{'─'*70}")
    print("PnL by hour (UTC)")
    all_hours = sorted(set(list(v1['pnl_by_hour'].keys()) + list(v2['pnl_by_hour'].keys())))
    for h in all_hours:
        h1 = v1['pnl_by_hour'].get(h, 0.0)
        h2 = v2['pnl_by_hour'].get(h, 0.0)
        bar1 = ("▓" * int(abs(h1) * 20)).rjust(10) if h1 < 0 else ""
        bar2 = ("░" * int(abs(h2) * 20)).ljust(10) if h2 > 0 else ""
        print(f"  {h:<10}{h1:>+10.3f}  {h2:>+10.3f}")

    print(f"\n{'─'*70}")
    print("PnL by edge bucket")
    for bucket in ["0.00-0.02", "0.02-0.05", "0.05+"]:
        h1 = v1['pnl_by_edge_bucket'].get(bucket, 0.0)
        h2 = v2['pnl_by_edge_bucket'].get(bucket, 0.0)
        print(f"  edge {bucket:<28}{h1:>+10.3f}  {h2:>+10.3f}")

    print(f"\n{'─'*70}")
    print("PnL by spread bucket")
    for bucket in ["0.00-0.02", "0.02-0.05", "0.05+"]:
        h1 = v1['pnl_by_spread_bucket'].get(bucket, 0.0)
        h2 = v2['pnl_by_spread_bucket'].get(bucket, 0.0)
        print(f"  spread {bucket:<26}{h1:>+10.3f}  {h2:>+10.3f}")

    print(f"\n{'─'*70}")
    print("Rejection reason summary")
    all_reasons = sorted(set(list(v1['reject_reasons'].keys()) + list(v2['reject_reasons'].keys())))
    if all_reasons:
        for r in all_reasons:
            n1 = v1['reject_reasons'].get(r, 0)
            n2 = v2['reject_reasons'].get(r, 0)
            print(f"  {r:<35}{n1:>10}{n2:>12}")
    else:
        print("  (none — risk manager passed all signals)")

    print(f"\n{'='*70}\n")


# ─────────────────────────────────────────────────────────────────────────────
# Main entry
# ─────────────────────────────────────────────────────────────────────────────

def run_replay(
    start: datetime,
    end: datetime,
    seed: int | None,
    runs: int,
    out_path: str | None,
    passive_fill_prob: float = 0.30,
) -> None:
    settings = get_settings()
    repo = SnapshotRepository()

    print(f"\n{'='*70}")
    print(f" REPLAY  {start.date()} → {end.date()}  |  runs={runs}  seed={seed}")
    print(f"{'='*70}\n")

    raw_rows = repo.get_snapshots_in_range(start, end)
    if not raw_rows:
        print("⚠  No snapshots found. Run the live stack to collect data first.\n")
        return

    resolutions = load_market_resolutions()
    resolved_count = sum(1 for v in resolutions.values() if v is not None)

    token_rows: dict[str, list] = defaultdict(list)
    for row in raw_rows:
        token_rows[row.token_id].append(row)

    total_scanned = len(set(r.market_id for r in raw_rows))
    print(f"📍 Markets with snapshots  : {total_scanned}")
    print(f"📸 Snapshots loaded        : {len(raw_rows)}")
    print(f"🪙 Unique tokens           : {len(token_rows)}")
    print(f"✅ Markets resolved in DB  : {resolved_count} / {len(resolutions)}")

    # Determine settlement quality
    any_true_resolution = any(resolutions.get(r.market_id) for r in raw_rows)
    print(f"🏁 Settlement mode         : {'TRUE + fallback' if any_true_resolution else 'midpoint fallback only'}\n")

    # Monte Carlo bookkeeping
    mc_pnl: dict[str, list[float]] = {s.name: [] for s in STRATEGIES}
    last_per_strategy: dict[str, dict] = {}
    all_trades: list[dict] = []

    for run_idx in range(runs):
        run_seed = (seed + run_idx) if seed is not None else None
        rng = random.Random(run_seed)

        per_strategy, trades = run_single(token_rows, resolutions, rng, passive_fill_prob)

        for sname in mc_pnl:
            mc_pnl[sname].append(per_strategy[sname]["realized_pnl"])

        # Tag trades with run index and seed
        for t in trades:
            t["run"] = run_idx
            t["seed"] = run_seed
        all_trades.extend(trades)
        last_per_strategy = per_strategy

        if runs > 1:
            # Brief per-run line
            v1p = per_strategy["eth_direction_15m_v1"]["realized_pnl"]
            v2p = per_strategy["eth_direction_15m_v2"]["realized_pnl"]
            print(f"  run {run_idx+1:>3}/{runs}  seed={run_seed}  V1={v1p:+.4f}  V2={v2p:+.4f}")

    # Full report (last run for per-bucket detail)
    print_report(last_per_strategy, mc_pnl if runs > 1 else None)

    # ── Export ──────────────────────────────────────────────────────────────
    if out_path:
        os.makedirs(os.path.dirname(out_path) if os.path.dirname(out_path) else ".", exist_ok=True)

        if out_path.endswith(".csv"):
            with open(out_path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=list(all_trades[0].keys()) if all_trades else [])
                writer.writeheader()
                writer.writerows(all_trades)
        else:
            # JSON (default)
            export = {
                "meta": {
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "runs": runs,
                    "seed": seed,
                    "snapshots_loaded": len(raw_rows),
                    "markets_scanned": total_scanned,
                    "settlement_mode": "true+fallback" if any_true_resolution else "midpoint_fallback",
                },
                "monte_carlo": {k: v for k, v in mc_pnl.items()},
                "last_run_stats": {
                    sn: {
                        **{k: v for k, v in st.items() if not isinstance(v, defaultdict)},
                        "reject_reasons": dict(st["reject_reasons"]),
                        "pnl_by_hour": dict(st["pnl_by_hour"]),
                    }
                    for sn, st in last_per_strategy.items()
                },
                "trades": all_trades,
            }
            with open(out_path, "w") as f:
                json.dump(export, f, indent=2, default=str)

        print(f"💾 Results exported to: {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay stored snapshots through all strategies.")
    parser.add_argument("--date",  type=str, help="Single date (YYYY-MM-DD)")
    parser.add_argument("--start", type=str, help="Start date inclusive (YYYY-MM-DD)")
    parser.add_argument("--end",   type=str, help="End date inclusive (YYYY-MM-DD)")
    parser.add_argument("--seed",  type=int, default=None, help="RNG seed for reproducibility")
    parser.add_argument("--runs",  type=int, default=1,    help="Number of Monte Carlo runs")
    parser.add_argument("--fill-prob", type=float, default=0.30,
                        help="Passive fill probability (default 0.30)")
    parser.add_argument("--out",   type=str, default=None,
                        help="Output path for results (*.json or *.csv)")
    args = parser.parse_args()

    if args.date:
        start = datetime.strptime(args.date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        end   = start + timedelta(days=1) - timedelta(seconds=1)
    elif args.start and args.end:
        start = datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        end   = datetime.strptime(args.end,   "%Y-%m-%d").replace(tzinfo=timezone.utc) \
                + timedelta(days=1) - timedelta(seconds=1)
    else:
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date()
        start = datetime(yesterday.year, yesterday.month, yesterday.day, tzinfo=timezone.utc)
        end   = start + timedelta(days=1) - timedelta(seconds=1)
        print(f"No date specified — defaulting to yesterday ({yesterday})")

    run_replay(start, end, args.seed, args.runs, args.out, args.fill_prob)


if __name__ == "__main__":
    main()
