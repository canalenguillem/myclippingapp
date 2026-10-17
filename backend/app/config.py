from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "mysql+pymysql://clipping:clipping@localhost:3306/clipping?charset=utf8mb4"
    jwt_secret: str = ""
    app_encryption_key: str = ""
    allow_registration: bool = True
    public_base_url: str = "http://localhost:5074"

    openai_api_key: str = ""
    openai_clip_model: str = "gpt-4o"
    aai_api_key: str = ""

    worker_concurrency: int = 2
    fx_worker_url: str = ""
    fx_parallel: int = 1
    media_dir: Path = Path("/media")


@lru_cache
def get_settings() -> Settings:
    return Settings()
