from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.router import api_router
from app.core.config import settings
from app.core.database import Base, SessionLocal, engine
from app.core.security import ensure_bootstrap_admin
from app import telegram_models  # noqa: F401 - registers Telegram tables on Base.metadata
from app import flow_channel_models  # noqa: F401 - registers shared channel-flow tables
from app import flow_graph_integrity  # noqa: F401 - registers flow graph integrity hooks
from app import http_api_models  # noqa: F401 - registers reusable HTTP API tables
from app import developer_api_models  # noqa: F401 - registers Developer API tables
from app import campaign_models  # noqa: F401 - registers reusable questionnaire campaigns
from app import default_action_models  # noqa: F401 - registers channel Default Actions
from app.flow_graph_integrity import repair_flow_start_nodes
from app.services.flow_http_diagnostics import install as install_flow_http_diagnostics
from app.services.whatsapp_interactive_snapshot import install as install_whatsapp_interactive_snapshot
from app.services.question_choices import install as install_question_choices
from app.services.campaign_runtime import install as install_campaign_runtime
from app.services.default_action_runtime import install as install_default_actions
from app.services.multi_trigger import install as install_multi_trigger
from app.services.telegram_dynamic_checkpoint import install as install_telegram_dynamic_checkpoint


@asynccontextmanager
async def lifespan(_: FastAPI):
    # v0.2.0 bootstrap. Alembic owns schema changes; create_all remains temporarily for legacy bootstrap compatibility.
    Base.metadata.create_all(bind=engine)
    install_flow_http_diagnostics()
    install_whatsapp_interactive_snapshot()
    install_question_choices()
    install_campaign_runtime()
    # A dynamic-list button choice is durable user input. Checkpoint it before
    # continuing to downstream nodes, and close a stale waiting session if a
    # later node fails.
    install_telegram_dynamic_checkpoint()
    # Default Actions wraps the channel matchers. Install it first, then let
    # multi-trigger replace the native keyword predicate used by that wrapper.
    install_default_actions()
    install_multi_trigger()
    with SessionLocal() as db:
        ensure_bootstrap_admin(db)
        repair_flow_start_nodes(db)
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
