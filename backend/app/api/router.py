from fastapi import APIRouter

from app.api.conversations import router as conversations_router
from app.api.webhooks import router as webhooks_router

api_router = APIRouter()
api_router.include_router(webhooks_router)
api_router.include_router(conversations_router)
