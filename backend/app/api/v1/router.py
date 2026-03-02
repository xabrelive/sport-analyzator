"""API v1."""
from fastapi import APIRouter

from app.api.v1 import matches, leagues, players, signals, probability, auth, time as time_api, me, sports, admin, statistics

api_router = APIRouter()

api_router.include_router(time_api.router, prefix="/time", tags=["time"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(me.router, prefix="/me", tags=["me"])
api_router.include_router(sports.router, prefix="/sports", tags=["sports"])
api_router.include_router(admin.router, prefix="/admin", tags=["admin"])
api_router.include_router(statistics.router, prefix="/statistics", tags=["statistics"])
api_router.include_router(matches.router, prefix="/matches", tags=["matches"])
api_router.include_router(leagues.router, prefix="/leagues", tags=["leagues"])
api_router.include_router(players.router, prefix="/players", tags=["players"])
api_router.include_router(signals.router, prefix="/signals", tags=["signals"])
api_router.include_router(probability.router, tags=["probability"])
