"""Application configuration. All options can be overridden via .env."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database (PostgreSQL — рассчитан на миллионы строк и сотни/тысячи записей в день)
    database_url: str = "postgresql://pingwin:pingwin@localhost:11002/pingwin"
    database_url_async: str | None = None

    # Auth
    secret_key: str = "change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24 * 7  # 7 days

    # Verification codes (email + Telegram)
    verification_code_expire_minutes: int = 15
    verification_code_length: int = 6

    # Frontend
    frontend_url: str = "http://localhost:11000"
    frontend_public_url: str = ""

    # CORS
    cors_extra_origins: str = ""

    # API
    api_v1_prefix: str = "/api/v1"
    debug: bool = False

    # SMTP (sending codes to email)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""
    smtp_use_tls: bool = True

    # Telegram Bot
    telegram_bot_token: str = ""
    telegram_bot_username: str = ""

    @property
    def async_database_url(self) -> str:
        if self.database_url_async:
            return self.database_url_async
        if self.database_url.startswith("postgresql://"):
            return self.database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return self.database_url

    @property
    def frontend_base_url(self) -> str:
        return (self.frontend_public_url or self.frontend_url or "").rstrip("/")


settings = Settings()
