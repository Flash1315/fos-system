from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Fos"
    secret_key: str = "dev-secret-change-me"
    database_url: str = "sqlite:///./fos.db"
    access_token_expire_minutes: int = 60 * 24 * 7
    cors_origins: str = "*"
    algorithm: str = "HS256"

    # Optional SMTP — when smtp_host is set, invite/reset emails are sent
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_use_tls: bool = True
    public_app_url: str = ""  # e.g. https://app.example.com — shown in invite emails

    # Media: local (default) or s3
    media_backend: str = "local"  # local | s3
    s3_bucket: str = ""
    s3_region: str = "us-east-1"
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_endpoint_url: str = ""  # MinIO / R2 compatible
    s3_public_base_url: str = ""  # optional CDN/public URL prefix

    # Optional Telegram bot for org notifications
    telegram_bot_token: str = ""

    # Allow POST /billing/plan stub switches (off by default)
    billing_plan_switch: bool = False

    # Process-local auth rate limits (disable in pytest)
    rate_limit_enabled: bool = True
    # Only honor X-Forwarded-For when the app sits behind a trusted reverse proxy
    trust_x_forwarded_for: bool = False
    # development | production — production refuses insecure defaults
    environment: str = "development"


settings = Settings()
