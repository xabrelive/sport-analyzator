"""API v1 router."""
from fastapi import APIRouter

from app.api.v1 import auth, me, table_tennis

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(me.router, prefix="/me", tags=["me"])
api_router.include_router(table_tennis.router, prefix="/table-tennis", tags=["table-tennis"])
