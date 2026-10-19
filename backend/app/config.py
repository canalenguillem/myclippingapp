from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "mysql+pymysql://clipping:clipping@localhost:3306/clipping?charset=utf8mb4"
    jwt_secret: str = ""
    app_encryption_key: str = ""
    allow_registration: bool = True
    login_window_seconds: int = 900         # ventana del límite de intentos de login
    login_max_per_email: int = 5            # fallos por email en la ventana
    login_max_per_ip: int = 20              # fallos por IP en la ventana (más holgado: varias personas pueden compartir IP)
    public_base_url: str = "http://localhost:5074"

    openai_api_key: str = ""
    openai_clip_model: str = "gpt-4o"
    aai_api_key: str = ""

    worker_concurrency: int = 2
    fx_worker_url: str = ""
    asd_worker_url: str = ""                # worker TalkNet en GPU (vacío = «Sigue al hablante» sin detección de cara)
    media_dir: Path = Path("/media")


@lru_cache
def get_settings() -> Settings:
    return Settings()
