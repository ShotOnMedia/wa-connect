from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.router import api_router
from app.core.config import settings
from app.core.database import Base, SessionLocal, engine
from app.core.security import ensure_bootstrap_admin
from app import telegram_models  # noqa: F401 - registers Telegram tables on Base.metadata


@asynccontextmanager
async def lifespan(_: FastAPI):
    # v0.2.0 bootstrap. Replace with Alembic migrations before production release.
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        ensure_bootstrap_admin(db)
    yield


app = FastAPI(title=settings.app_name, version=__version__, debug=settings.app_debug, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.api_prefix)


@app.get("/health")
def health():
    return {"status": "ok", "version": __version__}
