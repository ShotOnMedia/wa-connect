from fastapi import APIRouter, Depends

from app.api.auth import router as auth_router
from app.api.contact_fields import router as contact_fields_router
from app.api.contacts import router as contacts_router
from app.api.conversations import router as conversations_router
from app.api.flows import router as flows_router
from app.api.http_apis import router as http_apis_router
from app.api.settings import router as settings_router
from app.api.telegram import router as telegram_router
from app.api.telegram_webhooks import router as telegram_webhooks_router
from app.api.users import router as users_router
from app.api.webhooks import router as webhooks_router
from app.core.security import require_user

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(webhooks_router)
api_router.include_router(telegram_webhooks_router)
api_router.include_router(conversations_router, dependencies=[Depends(require_user)])
api_router.include_router(contacts_router, dependencies=[Depends(require_user)])
api_router.include_router(contact_fields_router, dependencies=[Depends(require_user)])
api_router.include_router(flows_router, dependencies=[Depends(require_user)])
api_router.include_router(http_apis_router)
api_router.include_router(settings_router, dependencies=[Depends(require_user)])
api_router.include_router(telegram_router)
api_router.include_router(users_router, dependencies=[Depends(require_user)])
