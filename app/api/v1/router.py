from fastapi import APIRouter
from app.api.v1.auth import router as auth_router
from app.api.v1.compare import router as compare_router
from app.api.v1.discounts import router as discounts_router
from app.api.v1.history import router as history_router
from app.api.v1.voice import router as voice_router
from app.api.v1.staples import router as staples_router

api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(auth_router, prefix="/auth", tags=["Authentication"])
api_v1_router.include_router(compare_router, prefix="/compare", tags=["Comparison"])
api_v1_router.include_router(discounts_router, prefix="/discounts", tags=["Discounts"])
api_v1_router.include_router(history_router, prefix="/history", tags=["Price History & Tracking"])
api_v1_router.include_router(voice_router, prefix="/voice", tags=["Voice & Google Home"])
api_v1_router.include_router(staples_router, prefix="/staples", tags=["Staples"])
