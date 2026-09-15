from functools import lru_cache
from typing import Annotated
from pydantic import BeforeValidator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

def parse_cors_origins(value):
    if isinstance(value,str):return [item.strip() for item in value.split(",") if item.strip()]
    return value
CorsOrigins=Annotated[list[str],NoDecode,BeforeValidator(parse_cors_origins)]
class Settings(BaseSettings):
    model_config=SettingsConfigDict(env_file=".env",extra="ignore")
    app_name:str="WA Connect";app_env:str="development";app_debug:bool=False;api_prefix:str="/api/v1"
    public_base_url:str="";inbound_media_dir:str="/app/storage/inbound-media";media_settings_encryption_key:str=""
    database_url:str="mysql+pymysql://wa_connect:wa_connect@db:3306/wa_connect";redis_url:str="redis://redis:6379/0"
    # Keep normal DB capacity large enough for concurrent API/webhook work, but
    # fail fast under genuine saturation instead of tying requests up for the
    # SQLAlchemy default 30 seconds. All values remain environment configurable.
    db_pool_size:int=10;db_max_overflow:int=10;db_pool_timeout:float=5.0;db_pool_recycle:int=1800
    # Telegram updates can perform long-running flow work. Bound concurrent
    # webhook execution so Telegram cannot consume every DB connection and
    # starve health/auth/live-chat traffic during a burst.
    telegram_webhook_concurrency:int=8;telegram_webhook_queue_timeout:float=2.0
    meta_graph_api_version:str="v23.0";meta_verify_token:str="change-me";meta_app_secret:str="";meta_access_token:str=""
    auth_cookie_name:str="wa_connect_session";auth_session_days:int=7;auth_cookie_secure:bool=True;bootstrap_admin_email:str="";bootstrap_admin_password:str="";bootstrap_admin_name:str="Administrator"
    cors_origins:CorsOrigins=["http://localhost:5173"]
@lru_cache
def get_settings()->Settings:return Settings()
settings=get_settings()
