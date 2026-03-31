import asyncio
import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from bot.data.repositories.reports import ReportRepository
from bot.core.market_profiles import MARKET_PROFILES, get_profile
from bot.core.config import get_settings

class ProfileComparator:
    def __init__(self, start: datetime, end: datetime):
        self.repo = ReportRepository()
        self.start = start
        self.end = end

    async def run_comparison(self, profile_names: list[str]) -> dict[str, Any]:
        results = {}
        
        for name in profile_names:
            print(f"Analyzing profile: {name}...", flush=True)
            try:
                profile = get_profile(name)
                # Fetch quality report filtered by profile
                # Note: get_universe_quality returns a dict grouped by key (e.g. 'total')
                raw_report_grouped = self.repo.get_universe_quality(
                    start=self.start,
                    end=self.end,
                    group_by="total",
                    market_profile=name
                )
                
                # Get the 'total' entry or the only entry if grouped by 'total'
                raw_report = raw_report_grouped.get("total", {})
                
                if not raw_report or raw_report.get("coverage", {}).get("total_snapshots") == 0:
                    results[name] = self._empty_result(name, profile.description)
                else:
                    results[name] = self._process_result(name, profile.description, raw_report)
                    
            except Exception as e:
                print(f"Error processing {name}: {e}", file=sys.stderr)
                results[name] = self._error_result(name, str(e))

        # Ranking
        ranked = self._rank_profiles(results)
        
        return {
            "comparison_metadata": {
                "generated_at": datetime.utcnow().isoformat(),
                "start_date": self.start.isoformat(),
                "end_date": self.end.isoformat(),
                "profiles_compared": profile_names
            },
            "profile_results": results,
            "ranking": ranked
        }

    def _empty_result(self, name: str, desc: str) -> dict:
        return {
            "profile_name": name,
            "profile_description": desc,
            "data_status": "no_data",
            "comparison_eligible": False,
            "eligibility_reason": "No snapshots found in the given range",
        }

    def _error_result(self, name: str, error: str) -> dict:
        return {
            "profile_name": name,
            "data_status": "error",
            "comparison_eligible": False,
            "eligibility_reason": f"Processing error: {error}",
        }

    def _process_result(self, name: str, desc: str, raw: dict) -> dict:
        cov = raw.get("coverage", {})
        snap = raw.get("snapshot_quality", {})
        fun = raw.get("opportunity_funnel", {})
        fail = raw.get("failure_analysis", {})
        verd = raw.get("universe_verdict", {})
        
        # Eligibility
        snap_count = cov.get("total_snapshots", 0)
        sig_count = cov.get("total_signals", 0)
        
        status = "comparable"
        eligible = True
        reason = "Sufficient data"
        
        if snap_count < 100:
            status = "insufficient_data"
            eligible = False
            reason = f"Low snapshot count ({snap_count} < 100)"
        elif sig_count < 10:
             status = "insufficient_data"
             eligible = False
             reason = f"Low signal count ({sig_count} < 10)"

        return {
            "profile_name": name,
            "profile_description": desc,
            "data_status": status,
            "comparison_eligible": eligible,
            "eligibility_reason": reason,
            "coverage": cov,
            "snapshot_quality": snap,
            "funnel_quality": fun,
            "failure_analysis": fail,
            "verdict": verd
        }

    def _rank_profiles(self, results: dict[str, Any]) -> dict:
        eligible_profiles = [r for r in results.values() if r.get("comparison_eligible")]
        
        scores = []
        for p in eligible_profiles:
            q = p["snapshot_quality"]
            f = p["funnel_quality"]
            c = p["coverage"]
            
            # Heuristic Score (0-100)
            # 1. Execution Viability (40%) - how many snaps meet spread/depth rules
            exec_ok_rate = q.get("pct_snapshots_meeting_exec_conditions", 0) * 100
            
            # 2. Funnel Efficiency (30%) - tradeable conversion
            conv_rate = f.get("tradeable_to_exec_approved_rate", 0) * 100
            
            # 3. Volume Factor (30%) - signal volume compared to a target of 50/day
            days = (self.end - self.start).days or 1
            target_signals = 50 * days
            volume_rate = min(1.0, c.get("total_signals", 0) / target_signals) * 100
            
            # Penalties
            penalty = 0
            if q.get("p90_spread", 0) > 0.15: penalty += 20
            if c.get("total_signals", 0) < 20: penalty += 15 # Low sample penalty
            
            score = (exec_ok_rate * 0.4) + (conv_rate * 0.3) + (volume_rate * 0.3) - penalty
            scores.append({
                "name": p["profile_name"],
                "score": float(f"{max(0, score):.2f}"),
                "metrics": {
                    "exec_ok_rate": float(f"{exec_ok_rate:.2f}"),
                    "conv_rate": float(f"{conv_rate:.2f}"),
                    "volume_rate": float(f"{volume_rate:.2f}")
                }
            })
            
        ranked = sorted(scores, key=lambda x: x["score"], reverse=True)
        
        top_profile = ranked[0]["name"] if ranked else None
        rationale = ""
        if ranked:
            top = ranked[0]
            rationale = f"Profile '{top['name']}' leads with score {top['score']}. "
            # Heuristic check for structural viability
            if isinstance(top, dict) and top.get("metrics", {}).get("exec_ok_rate", 0) > 50:
                 rationale += "High structural viability observed. "
            else:
                 rationale += "Ranking is relative; all profiles show viability challenges. "
        else:
            rationale = "No profiles were eligible for ranking due to missing or insufficient data."

        return {
            "ranked_profiles": ranked,
            "top_profile": top_profile,
            "ranking_rationale": rationale,
            "recommended_next_profile_for_collection": top_profile if top_profile != "eth_15m_direction" else "none"
        }

    def determine_challenger_status(self, results: dict, baseline: str, challenger: str) -> dict:
        """Explicitly compare challenger vs baseline for decision making."""
        b = results.get(baseline)
        c = results.get(challenger)
        
        if not b or not c:
            return {"status": "error", "message": "Missing baseline or challenger data."}
            
        if c["data_status"] == "insufficient_data":
            return {"status": "insufficient_data", "message": f"Challenger {challenger} has insufficient data."}
            
        b_score = next((r["score"] for r in results["ranking"]["ranked_profiles"] if r["name"] == baseline), 0)
        c_score = next((r["score"] for r in results["ranking"]["ranked_profiles"] if r["name"] == challenger), 0)
        
        diff = c_score - b_score
        
        if diff > 10:
            status = "BETTER"
            msg = f"Challenger {challenger} is significantly better than baseline (+{diff:.1f} pts)."
        elif diff < -10:
            status = "WORSE"
            msg = f"Challenger {challenger} is significantly worse than baseline ({diff:.1f} pts)."
        else:
            status = "COMPARABLE"
            msg = f"Challenger {challenger} is comparable to baseline (diff {diff:+.1f} pts)."
            
        return {
            "status": status,
            "message": msg,
            "baseline_score": b_score,
            "challenger_score": c_score,
            "diff": diff
        }

def print_comparison_table(results: dict[str, Any]):
    print("\n" + "="*80)
    print(f"{'PROFILE':<25} | {'STATUS':<15} | {'SNAP OK':<10} | {'CONV':<10} | {'SIGNALS':<10}")
    print("-" * 80)
    for name, res in results["profile_results"].items():
        status = res["data_status"]
        if status == "comparable":
            q = res["snapshot_quality"]
            f = res["funnel_quality"]
            c = res["coverage"]
            ok_rate = f"{q.get('pct_snapshots_meeting_exec_conditions', 0)*100:.1f}%"
            conv = f"{f.get('tradeable_to_exec_approved_rate', 0)*100:.1f}%"
            sigs = c.get("total_signals", 0)
            print(f"{name:<25} | {status:<15} | {ok_rate:<10} | {conv:<10} | {sigs:<10}")
        else:
            print(f"{name:<25} | {status:<15} | {'-':<10} | {'-':<10} | {'-':<10}")
    print("="*80)
    
    ranking = results["ranking"]
    if ranking["ranked_profiles"]:
        print(f"\n🏆 TOP PROFILE: {ranking['top_profile']}")
        print(f"Rationale: {ranking['ranking_rationale']}")
    else:
        print("\nNo ranking available (insufficient data).")

    if "challenger_evaluation" in results:
        eval = results["challenger_evaluation"]
        print(f"\n🏁 CHALLENGER EVALUATION: {eval['status']}")
        print(f"  - {eval['message']}")
        print(f"  - Baseline   : {eval.get('baseline_score', 0):.2f}")
        print(f"  - Challenger : {eval.get('challenger_score', 0):.2f}")

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=str, default="eth_15m_direction", help="Baseline profile name")
    parser.add_argument("--challenger", type=str, default="btc_1h_direction", help="Challenger profile name")
    parser.add_argument("--start", type=str, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, help="End date (YYYY-MM-DD)")
    parser.add_argument("--out", type=str, default="results/profile_comparison/comparison_report.json")
    args = parser.parse_args()

    # Profiles to compare
    profiles = list(set([args.baseline, args.challenger] + ["eth_15m_direction", "btc_15m_direction", "btc_1h_direction", "eth_daily_direction"]))

    # Dates
    if args.end:
        end = datetime.strptime(args.end, "%Y-%m-%d")
    else:
        end = datetime.now(timezone.utc).replace(tzinfo=None)
        
    if args.start:
        start = datetime.strptime(args.start, "%Y-%m-%d")
    else:
        start = end - timedelta(days=7)

    comparator = ProfileComparator(start, end)
    report = await comparator.run_comparison(profiles)
    
    # Challenger Status
    challenger_status = comparator.determine_challenger_status(report["profile_results"] | {"ranking": report["ranking"]}, args.baseline, args.challenger)
    report["challenger_evaluation"] = challenger_status
    
    # Save JSON
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2)
    
    print_comparison_table(report)
    print(f"\nFull report saved to: {args.out}")

if __name__ == "__main__":
    asyncio.run(main())
