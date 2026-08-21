from functools import lru_cache
from typing import Annotated

from pydantic import BeforeValidator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


def parse_cors_origins(value):
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return value


CorsOrigins = Annotated[list[str], NoDecode, BeforeValidator(parse_cors_origins)]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "WA Connect"
    app_env: str = "development"
    app_debug: bool = False
    api_prefix: str = "/api/v1"

    database_url: str = "mysql+pymysql://wa_connect:wa_connect@db:3306/wa_connect"
    redis_url: str = "redis://redis:6379/0"

    meta_graph_api_version: str = "v23.0"
    meta_verify_token: str = "change-me"
    meta_app_secret: str = ""
    meta_access_token: str = ""

    cors_origins: CorsOrigins = ["http://localhost:5173"]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
