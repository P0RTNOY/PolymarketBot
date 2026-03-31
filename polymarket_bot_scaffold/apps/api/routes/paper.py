from fastapi import APIRouter
from bot.data.repositories.paper import PaperRepository
from bot.data.repositories.reports import ReportRepository

router = APIRouter()
repo = PaperRepository()
reports_repo = ReportRepository()

@router.get("/daily_report")
def get_daily_report():
    data = reports_repo.get_daily_report()
    return {
        "status": "ok",
        "data": data
    }

@router.get("/stats")
def get_paper_stats():
    stats = repo.get_stats()
    return {
        "status": "ok",
        "data": stats
    }

@router.get("/universe_quality")
def get_universe_quality(
    start_date: str | None = None, 
    end_date: str | None = None, 
    group_by: str = "date",
    strategy_version: str | None = None
):
    from datetime import datetime
    start = datetime.fromisoformat(start_date) if start_date else None
    end = datetime.fromisoformat(end_date) if end_date else None
    
    data = reports_repo.get_universe_quality(
        start=start, 
        end=end, 
        group_by=group_by, 
        strategy_version=strategy_version
    )
    return {
        "status": "ok",
        "data": data
    }
