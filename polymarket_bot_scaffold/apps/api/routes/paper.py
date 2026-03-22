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
