from datetime import datetime, timezone, timedelta
import statistics
import json
from sqlalchemy import select, func, text, and_
from bot.data.session import SessionLocal
from bot.data.models import SignalRecord, PaperOrder, PaperPosition, MarketSnapshot, Market
from bot.analytics.candidate_buckets import EDGE_BUCKET_LABELS, TRADEABLE, CANDIDATE
from bot.core.config import get_settings
from bot.core.market_profiles import get_profile, ProfileMatcher

class ReportRepository:
    def get_daily_report(self) -> dict:
        now = datetime.now(timezone.utc)
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        start_24h = now - timedelta(hours=24)

        with SessionLocal() as session:
            # 1. Scanned markets (unique markets with a snapshot in last 24h)
            scanned = session.scalar(
                select(func.count(func.distinct(MarketSnapshot.market_id)))
                .where(MarketSnapshot.timestamp >= start_24h)
            ) or 0

            # 2. Signals generated in last 24h
            signals_24h = session.scalars(
                select(SignalRecord)
                .where(SignalRecord.timestamp >= start_24h)
            ).all()
            total_signals = len(signals_24h)

            # Rejections
            rejection_reasons = {}
            passed_risk = 0
            for sig in signals_24h:
                if sig.eval_status == "REJECTED":
                    r = sig.eval_reason or "unknown"
                    # simplify dynamic reasons (e.g. spread_too_wide(0.09) -> spread_too_wide)
                    base_r = r.split("(")[0]
                    rejection_reasons[base_r] = rejection_reasons.get(base_r, 0) + 1
                elif sig.eval_status == "ACCEPTED":
                    passed_risk += 1

            # 3. Orders placed and filled in last 24h
            orders_24h = session.scalars(
                select(PaperOrder)
                .where(PaperOrder.created_at >= start_24h)
            ).all()
            total_orders = len(orders_24h)
            filled_orders = [o for o in orders_24h if o.status == "FILLED"]
            total_filled = len(filled_orders)

            # Average fill delay
            total_delay_secs = sum(
                (o.filled_at - o.created_at).total_seconds() 
                for o in filled_orders if o.filled_at and o.created_at
            )
            avg_fill_delay_secs = (total_delay_secs / total_filled) if total_filled > 0 else 0.0

            # 4. Position metrics (Closed in 24h)
            closed_24h = session.scalars(
                select(PaperPosition)
                .where(PaperPosition.status == "CLOSED")
                .where(PaperPosition.closed_at >= start_24h)
            ).all()
            
            realized_pnl = sum(p.realized_pnl for p in closed_24h)
            best_trade = max((p.realized_pnl for p in closed_24h), default=0.0)
            worst_trade = min((p.realized_pnl for p in closed_24h), default=0.0)

            # PnL by UTC Hour
            pnl_by_hour = {}
            for p in closed_24h:
                if p.closed_at:
                    hour_str = p.closed_at.strftime("%H:00")
                    pnl_by_hour[hour_str] = pnl_by_hour.get(hour_str, 0.0) + p.realized_pnl

            # 5. Dynamic Unrealized PnL 
            open_positions = session.scalars(
                select(PaperPosition).where(PaperPosition.status == "OPEN")
            ).all()
            
            unrealized_pnl = 0.0
            for p in open_positions:
                # Find latest midpoint
                latest_snap = session.scalars(
                    select(MarketSnapshot)
                    .where(MarketSnapshot.market_id == p.market_id)
                    .where(MarketSnapshot.token_id == p.token_id)
                    .order_by(MarketSnapshot.timestamp.desc())
                    .limit(1)
                ).first()

                if latest_snap:
                    # Unrealized logic: if we hold BUY_YES, value is midpoint.
                    # Price is between 0 and 1
                    current_val = latest_snap.midpoint if p.side == "BUY_YES" else (1.0 - latest_snap.midpoint)
                    u_pnl = (current_val - p.average_entry_price) * p.size_shares
                    unrealized_pnl += u_pnl

            # 6. Candidate bucket breakdown (Phase 12.1)
            candidate_rows = list(session.execute(
                select(SignalRecord.edge_bucket, SignalRecord.candidate_status)
                .where(SignalRecord.timestamp >= start_24h)
                .where(SignalRecord.candidate_status.is_not(None))
            ))

            candidates_by_bucket: dict[str, int] = {label: 0 for label in EDGE_BUCKET_LABELS}
            tradeable_by_bucket:  dict[str, int] = {label: 0 for label in EDGE_BUCKET_LABELS}
            total_candidates = 0
            total_tradeable  = 0

            for bucket, status in candidate_rows:
                if bucket and bucket in candidates_by_bucket:
                    candidates_by_bucket[bucket] += 1
                    total_candidates += 1
                    if status == TRADEABLE:
                        tradeable_by_bucket[bucket] += 1
                        total_tradeable += 1

            # 7. Exec rejection reason breakdown (Phase 12.2)
            exec_rejected_rows = list(session.execute(
                select(SignalRecord.exec_reasons)
                .where(SignalRecord.timestamp >= start_24h)
                .where(SignalRecord.exec_approved == False)  # noqa: E712
            ))
            exec_rejection_breakdown: dict[str, int] = {}
            import json as _json
            for (reasons_json,) in exec_rejected_rows:
                if reasons_json:
                    try:
                        reasons = _json.loads(reasons_json)
                        for r in reasons:
                            base = r.split("(")[0]
                            exec_rejection_breakdown[base] = exec_rejection_breakdown.get(base, 0) + 1
                    except Exception:
                        pass

            return {
                "markets_scanned_24h": scanned,
                "signals_generated_24h": total_signals,
                "signals_passed_risk": passed_risk,
                "rejection_reasons_summary": rejection_reasons,
                "orders_placed_24h": total_orders,
                "orders_filled_24h": total_filled,
                "average_fill_delay_secs": avg_fill_delay_secs,
                "realized_pnl_24h": realized_pnl,
                "unrealized_pnl_open": unrealized_pnl,
                "best_trade_pnl": best_trade,
                "worst_trade_pnl": worst_trade,
                "pnl_by_hour_utc": pnl_by_hour,
                # Phase 12.1 additions
                "candidates_total_24h": total_candidates,
                "tradeables_total_24h": total_tradeable,
                "candidates_by_edge_bucket": candidates_by_bucket,
                "tradeables_by_edge_bucket": tradeable_by_bucket,
                # Phase 12.2 additions
                "exec_rejection_breakdown": exec_rejection_breakdown,
            }

    def get_universe_quality(
        self, 
        start: datetime | None = None, 
        end: datetime | None = None, 
        group_by: str = "date",
        strategy_version: str | None = None,
        market_profile: str | None = None
    ) -> dict:
        settings = get_settings()
        
        # 1. Base Query Filters
        with SessionLocal() as session:
            snap_stmt = select(MarketSnapshot)
            sig_stmt = select(SignalRecord)
            
            if start:
                snap_stmt = snap_stmt.where(MarketSnapshot.timestamp >= start)
                sig_stmt = sig_stmt.where(SignalRecord.timestamp >= start)
            if end:
                snap_stmt = snap_stmt.where(MarketSnapshot.timestamp <= end)
                sig_stmt = sig_stmt.where(SignalRecord.timestamp <= end)
            if strategy_version:
                sig_stmt = sig_stmt.where(SignalRecord.strategy_name == strategy_version)
                
            snapshots = session.scalars(snap_stmt).all()
            signals = session.scalars(sig_stmt).all()
            
            # --- Profile Filtering (Phase 12.4 Addition) ---
            if market_profile:
                profile_obj = get_profile(market_profile)
                matcher = ProfileMatcher(profile_obj)
                
                # Fetch all markets referenced by these snapshots/signals
                m_ids = set([s.market_id for s in snapshots] + [sig.market_id for sig in signals])
                if not m_ids:
                    return {}
                
                m_stmt = select(Market).where(Market.id.in_(list(m_ids)))
                ref_markets = session.scalars(m_stmt).all()
                
                # Pre-calculate which markets match the profile
                match_map = {}
                for m in ref_markets:
                    # Convert Market model to dict for ProfileMatcher
                    m_dict = {
                        "question": m.question,
                        "slug": m.raw_json.get("slug", "") if m.raw_json else "",
                        "tokens": [] # Tokens not strictly required for current profile matching asset/horizon/dir
                    }
                    if m.raw_json and "tokens" in m.raw_json:
                         # Try to extract tokens if needed for binary check
                         # But for comparison we primarily care about asset/horizon
                         m_dict["tokens"] = m.raw_json.get("tokens", [])

                    match_map[m.id] = matcher.matches(m_dict)
                
                # Filter in memory
                snapshots = [s for s in snapshots if match_map.get(s.market_id, False)]
                signals = [s for s in signals if match_map.get(s.market_id, False)]
            # ---------------------------------------------
            
            # Helper: Get group key
            def get_group_key(ts: datetime, mid: str) -> str:
                if group_by == "date":
                    return ts.strftime("%Y-%m-%d")
                elif group_by == "hour":
                    return ts.strftime("%Y-%m-%d %H:00")
                elif group_by == "market_id":
                    return mid
                return "total"

            # 2. Aggregation Containers
            # Grouped by date/hour/market
            group_stats: dict[str, dict] = {}

            # 3. Process Snapshots
            for snap in snapshots:
                key = get_group_key(snap.timestamp, snap.market_id)
                if key not in group_stats:
                    group_stats[key] = {
                        "coverage": {"snapshot_count": 0, "signal_count": 0, "market_ids": set()},
                        "raw_snapshots": {"spreads": [], "depths": [], "stability_labels": []},
                        "snapshot_quality": {
                            "snapshots_under_spread": 0,
                            "snapshots_above_depth": 0,
                            "snapshots_exec_ok": 0
                        },
                        "funnel": {
                            "total_candidates": 0,
                            "tradeable": 0,
                            "exec_approved": 0,
                            "risk_approved": 0,
                            "tradability_scores": [],
                            "stability_scores": [],
                            "recent_tradable_ratios": [],
                            "streaks": []
                        },
                        "failures": {
                            "exec": {},
                            "risk": {}
                        }
                    }
                
                s = group_stats[key]
                s["coverage"]["snapshot_count"] += 1
                s["coverage"]["market_ids"].add(snap.market_id)
                
                # Raw metrics for percentiles
                s["raw_snapshots"]["spreads"].append(snap.spread)
                s["raw_snapshots"]["depths"].append(snap.bid_depth_usd + snap.ask_depth_usd)
                
                # Check snapshot-level exec conditions
                spread_ok = snap.spread < settings.max_spread
                depth_ok = (snap.bid_depth_usd + snap.ask_depth_usd) >= settings.min_depth_usd
                # Assuming staleness check would usually pass in historical lookback 
                # but we can check if it's within a reasonable window from 'now' 
                # or just use the raw fields we have.
                if spread_ok: s["snapshot_quality"]["snapshots_under_spread"] += 1
                if depth_ok: s["snapshot_quality"]["snapshots_above_depth"] += 1
                if spread_ok and depth_ok:
                    s["snapshot_quality"]["snapshots_exec_ok"] += 1

            # 4. Process Signals
            for sig in signals:
                key = get_group_key(sig.timestamp, sig.market_id)
                if key not in group_stats:
                    continue # Should theoretically be covered by snapshot key logic
                
                s = group_stats[key]
                s["coverage"]["signal_count"] += 1
                
                # Funnel logic
                if sig.candidate_status:
                    s["funnel"]["total_candidates"] += 1
                    if sig.candidate_status == TRADEABLE:
                        s["funnel"]["tradeable"] += 1
                
                if sig.exec_approved:
                    s["funnel"]["exec_approved"] += 1
                else:
                    # Failure analysis - exec
                    if sig.exec_reasons:
                        try:
                            reasons = json.loads(sig.exec_reasons)
                            for r in reasons:
                                base = r.split("(")[0]
                                s["failures"]["exec"][base] = s["failures"]["exec"].get(base, 0) + 1
                        except: pass
                
                if sig.eval_status == "ACCEPTED":
                    s["funnel"]["risk_approved"] += 1
                elif sig.eval_status == "REJECTED":
                    # Failure analysis - risk
                    r = sig.eval_reason or "unknown"
                    base = r.split("(")[0]
                    s["failures"]["risk"][base] = s["failures"]["risk"].get(base, 0) + 1

                # Scores
                if sig.exec_stability_score is not None:
                    s["funnel"]["stability_scores"].append(sig.exec_stability_score)
                if sig.exec_recent_tradable_ratio is not None:
                    s["funnel"]["recent_tradable_ratios"].append(sig.exec_recent_tradable_ratio)
                if sig.exec_consecutive_tradable_snapshots is not None:
                    s["funnel"]["streaks"].append(sig.exec_consecutive_tradable_snapshots)
                
                # Stability Label Distribution (from snapshot logic or signal logging)
                if sig.exec_stability_label:
                    s["raw_snapshots"]["stability_labels"].append(sig.exec_stability_label)

            # 5. Final Calculation
            final_report = {}
            for key, stats in group_stats.items():
                snap_count = stats["coverage"]["snapshot_count"]
                sig_count = stats["coverage"]["signal_count"]
                
                # Coverage Section
                coverage = {
                    "total_snapshots": snap_count,
                    "total_signals": sig_count,
                    "market_count": len(stats["coverage"]["market_ids"])
                }
                
                # Snapshot Quality Section
                raw = stats["raw_snapshots"]
                spreads = sorted(raw["spreads"])
                depths = sorted(raw["depths"])
                
                def get_p(data, p):
                    if not data: return 0.0
                    idx = int(len(data) * (p/100))
                    return data[min(len(data)-1, idx)]

                snap_quality = {
                    "median_spread": statistics.median(spreads) if spreads else 0.0,
                    "p90_spread": get_p(spreads, 90),
                    "min_spread": min(spreads) if spreads else 0.0,
                    "max_spread": max(spreads) if spreads else 0.0,
                    "pct_snapshots_under_max_spread": (stats["snapshot_quality"]["snapshots_under_spread"] / snap_count) if snap_count > 0 else 0.0,
                    "median_total_depth_usd": statistics.median(depths) if depths else 0.0,
                    "p10_total_depth_usd": get_p(depths, 10),
                    "max_total_depth_usd": max(depths) if depths else 0.0,
                    "pct_snapshots_above_min_depth_usd": (stats["snapshot_quality"]["snapshots_above_depth"] / snap_count) if snap_count > 0 else 0.0,
                    "pct_snapshots_meeting_exec_conditions": (stats["snapshot_quality"]["snapshots_exec_ok"] / snap_count) if snap_count > 0 else 0.0,
                }
                
                # Stability Label distribution
                labels = raw["stability_labels"]
                label_dist = {}
                if labels:
                    label_dist[l] = label_dist.get(l, 0) + 1
                for l in label_dist:
                    val = float(label_dist[l]) / len(labels)
                    label_dist[l] = round(val, 4)
                snap_quality["stability_label_distribution"] = label_dist

                # Funnel Section
                fn = stats["funnel"]
                funnel = {
                    "total_candidates": fn["total_candidates"],
                    "total_tradeable": fn["tradeable"],
                    "total_exec_approved": fn["exec_approved"],
                    "total_risk_approved": fn["risk_approved"],
                    "candidate_to_tradeable_rate": (fn["tradeable"] / fn["total_candidates"]) if fn["total_candidates"] > 0 else 0.0,
                    "tradeable_to_exec_approved_rate": (fn["exec_approved"] / fn["tradeable"]) if fn["tradeable"] > 0 else 0.0,
                    "execution_to_risk_approved_rate": (fn["risk_approved"] / fn["exec_approved"]) if fn["exec_approved"] > 0 else 0.0,
                    "avg_stability_score": statistics.mean(fn["stability_scores"]) if fn["stability_scores"] else 0.0,
                    "avg_recent_tradable_ratio": statistics.mean(fn["recent_tradable_ratios"]) if fn["recent_tradable_ratios"] else 0.0,
                    "median_consecutive_tradable_snapshots": statistics.median(fn["streaks"]) if fn["streaks"] else 0
                }
                
                # Failure Section
                failures = stats["failures"]
                def get_dominant(d):
                    if not d: return "none"
                    return max(d.items(), key=lambda x: x[1])[0]
                
                failure_analysis = {
                    "exec_rejection_reason_distribution": failures["exec"],
                    "risk_rejection_reason_distribution": failures["risk"],
                    "dominant_exec_rejection_reason": get_dominant(failures["exec"]),
                    "dominant_risk_rejection_reason": get_dominant(failures["risk"])
                }
                
                # Verdict Section (Heuristic)
                verdict = {
                    "universe_status": "viable",
                    "primary_bottleneck": "none",
                    "recommended_action": "continue_collecting"
                }
                
                exec_ok_rate = snap_quality["pct_snapshots_meeting_exec_conditions"]
                spread_p90 = snap_quality["p90_spread"]
                depth_med = snap_quality["median_total_depth_usd"]
                
                if exec_ok_rate < 0.05:
                    verdict["universe_status"] = "poor"
                    verdict["recommended_action"] = "pivot_profile"
                elif exec_ok_rate < 0.20:
                    verdict["universe_status"] = "borderline"
                    verdict["recommended_action"] = "continue_and_compare_profile"
                
                # Identify bottleneck
                if verdict["universe_status"] != "viable":
                    if failure_analysis["dominant_exec_rejection_reason"] == "spread_too_wide":
                        verdict["primary_bottleneck"] = "spread"
                    elif failure_analysis["dominant_exec_rejection_reason"] == "insufficient_depth":
                        verdict["primary_bottleneck"] = "depth"
                    elif "flicker" in label_dist or "unstable" in label_dist:
                        # If instability ratio is high
                        instability_ratio = label_dist.get("unstable", 0.0) + label_dist.get("flicker", 0.0)
                        if instability_ratio > 0.5:
                            verdict["primary_bottleneck"] = "instability"
                    else:
                        verdict["primary_bottleneck"] = "mixed"

                final_report[key] = {
                    "coverage": coverage,
                    "snapshot_quality": snap_quality,
                    "opportunity_funnel": funnel,
                    "failure_analysis": failure_analysis,
                    "universe_verdict": verdict
                }

            return final_report
