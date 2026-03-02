"""Server time for "data time" display."""
from datetime import datetime, timezone

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class ServerTimeResponse(BaseModel):
    iso: str
    timezone: str = "UTC"


@router.get("", response_model=ServerTimeResponse)
async def get_server_time() -> ServerTimeResponse:
    """Текущее время сервера (UTC) — для отображения «время данных»."""
    now = datetime.now(timezone.utc)
    return ServerTimeResponse(iso=now.isoformat(), timezone="UTC")
