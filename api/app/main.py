from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.alembic_runner import run_alembic_upgrade
from app.config import settings
from app.db import Base, engine
from app.migrate import ensure_money_record_columns
from app.routers import auth as auth_router
from app.routers import adjustments as adjustments_router
from app.routers import billing as billing_router
from app.routers import media as media_router
from app.routers import payouts as payouts_router
from app.routers import records as records_router
from app.routers import reports as reports_router
from app.routers import team as team_router
from app.routers import transfers as transfers_router

Base.metadata.create_all(bind=engine)
ensure_money_record_columns()
run_alembic_upgrade()

app = FastAPI(title=settings.app_name, version="0.7.7")

origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins if origins != ["*"] else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router.router)
app.include_router(records_router.router)
app.include_router(team_router.router)
app.include_router(reports_router.router)
app.include_router(media_router.router)
app.include_router(transfers_router.router)
app.include_router(payouts_router.router)
app.include_router(adjustments_router.router)
app.include_router(billing_router.router)


@app.get("/health")
def health():
    return {
        "ok": True,
        "app": settings.app_name,
        "version": "0.7.7",
        "media_backend": (settings.media_backend or "local").strip().lower(),
    }


if settings.secret_key in ("dev-secret-change-me", "change-me-in-production", ""):
    print("WARNING: SECRET_KEY is insecure — set a strong SECRET_KEY in production")
