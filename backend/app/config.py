from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    app_name: str = "AMBS Outreach"
    database_url: str
    jwt_secret: str
    jwt_expire_minutes: int = 480
    initial_admin_email: str = ""
    initial_admin_password: str = ""
    openai_api_key: str = ""
    openai_model: str = "gpt-5.4-mini"
    cors_origins: str = "http://localhost:5173"
    dry_run: bool = True
    emelia_api_key: str = ""
    emelia_api_url: str = "https://graphql.emelia.io/graphql"
    emelia_sender_email: str = "ambs.suivi@ambs-ia.com"
    isendpro_key_id: str = ""
    isendpro_api_url: str = "https://apirest.isendpro.com/cgi-bin"
    ambs_api_key: str = ""
    ambs_api_url: str = ""
    ambs_sender_id: str = ""
    model_config = SettingsConfigDict(env_file=BACKEND_ROOT / ".env", extra="ignore")

    @property
    def allowed_origins(self) -> list[str]:
        return [value.strip() for value in self.cors_origins.split(",") if value.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
