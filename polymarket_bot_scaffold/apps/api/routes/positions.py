from fastapi import APIRouter

router = APIRouter()

@router.get("")
def list_positions() -> dict:
    return {"items": [], "count": 0, "note": "Wire this route to the database repository."}
