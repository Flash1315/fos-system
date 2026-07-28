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
    s3_public_base_url: str = ""  # reserved; media always streams via authenticated API

    # Optional Telegram bot for org notifications
    telegram_bot_token: str = ""

    # Allow POST /billing/plan stub switches (off by default)
    billing_plan_switch: bool = False

    # Process-local auth rate limits (disable in pytest)
    rate_limit_enabled: bool = True
    # Only honor X-Forwarded-For when the app sits behind a trusted reverse proxy
    trust_x_forwarded_for: bool = False
    # Comma-separated CIDRs/IPs that may set X-Forwarded-For (empty = legacy trust-any when enabled)
    trusted_proxy_cidrs: str = ""
    # development | production — production refuses insecure defaults
    environment: str = "development"
    # Soft ceiling for org-wide member loops (balances / directory / reports)
    max_org_members: int = 300
    # Optional HSTS (enable only behind HTTPS terminators)
    enable_hsts: bool = False
    hsts_max_age: int = 31_536_000
    # Drop idempotency rows older than this (hours)
    idempotency_ttl_hours: int = 72

    # Postgres pool / SSL (ignored for SQLite)
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_recycle: int = 1800
    db_pool_timeout: int = 30
    db_connect_timeout: int = 10
    # Appended via connect_args when not already in DATABASE_URL (e.g. require)
    db_sslmode: str = ""

    # Optional Redis for shared rate limits across workers
    rate_limit_redis_url: str = ""


settings = Settings()
