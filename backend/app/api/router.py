from fastapi import APIRouter, Depends

from app.api.auth import router as auth_router
from app.api.conversations import router as conversations_router
from app.api.settings import router as settings_router
from app.api.webhooks import router as webhooks_router
from app.core.security import require_user

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(webhooks_router)
api_router.include_router(conversations_router, dependencies=[Depends(require_user)])
api_router.include_router(settings_router, dependencies=[Depends(require_user)])
