from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Fos"
    secret_key: str = "dev-secret-change-me"
    database_url: str = "sqlite:///./fos.db"
    access_token_expire_minutes: int = 60 * 24 * 7
    cors_origins: str = "*"
    algorithm: str = "HS256"


settings = Settings()
