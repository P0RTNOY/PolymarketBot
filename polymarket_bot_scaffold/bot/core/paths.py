"""
Centralized path helpers for profile-aware experiment outputs.
"""
from pathlib import Path

def get_profile_results_dir(profile_name: str) -> Path:
    """Returns results/profiles/{profile_name}"""
    return Path(f"results/profiles/{profile_name}")

def get_profile_manifest_path(profile_name: str) -> Path:
    """Returns results/profiles/{profile_name}/manifests/experiment_manifest.json"""
    return get_profile_results_dir(profile_name) / "manifests" / "experiment_manifest.json"

def get_profile_summary_path(profile_name: str) -> Path:
    """Returns results/profiles/{profile_name}/summaries/daily_summary.csv"""
    return get_profile_results_dir(profile_name) / "summaries" / "daily_summary.csv"

def resolve_daily_output_paths(profile_name: str, base_name: str, is_range: bool = False) -> tuple[Path, Path]:
    """
    Returns isolated Path objects for JSON and CSV replay outputs.
    Format: results/profiles/{profile_name}/{daily|weekly}/{base_name}.{json|csv}
    """
    subdir = "weekly" if is_range else "daily"
    base_dir = get_profile_results_dir(profile_name) / subdir
    
    json_path = base_dir / f"{base_name}.json"
    csv_path  = base_dir / f"{base_name}.csv"
    
    return json_path, csv_path
