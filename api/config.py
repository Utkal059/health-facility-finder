from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    allowed_origins: str = "http://localhost:5173"
    rate_limit_per_minute: int = 60
    trust_proxy_headers: bool = False
    db_pool_size: int = 10

    @property
    def cors_origins(self) -> list[str]:
        # Browsers send an origin without a trailing slash, so one pasted with it would never match.
        origins = (origin.strip().rstrip("/") for origin in self.allowed_origins.split(","))
        return [origin for origin in origins if origin]


@lru_cache
def get_settings() -> Settings:
    return Settings()
