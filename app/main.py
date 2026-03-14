from __future__ import annotations

from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import Base, engine, get_db
from app.models import SystemEvent, TokenWatch, WalletCandidate
from app.service import SmartWalletService

app = FastAPI(title=settings.app_name)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")
service = SmartWalletService()
scheduler = AsyncIOScheduler()


@app.on_event("startup")
async def startup_event():
    Base.metadata.create_all(bind=engine)

    scheduler.add_job(scheduled_trending_scan, IntervalTrigger(minutes=settings.trending_scan_minutes))
    scheduler.add_job(
        scheduled_daily_scan,
        CronTrigger(hour=settings.wallet_daily_scan_hour_utc, minute=0),
    )
    scheduler.start()


@app.on_event("shutdown")
def shutdown_event():
    scheduler.shutdown(wait=False)


async def scheduled_trending_scan():
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        await service.run_trending_pipeline(db)
    finally:
        db.close()


async def scheduled_daily_scan():
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        await service.run_daily_pipeline(db)
    finally:
        db.close()


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    formal = db.scalars(
        select(WalletCandidate)
        .where(WalletCandidate.formal_whitelist == 1)
        .order_by(desc(WalletCandidate.smart_score))
    ).all()
    prelist = db.scalars(select(WalletCandidate).order_by(desc(WalletCandidate.smart_score)).limit(150)).all()
    tokens = db.scalars(select(TokenWatch).order_by(desc(TokenWatch.discovered_at)).limit(50)).all()
    events = db.scalars(select(SystemEvent).order_by(desc(SystemEvent.created_at)).limit(20)).all()

    now = datetime.utcnow()
    token_rows = []
    for t in tokens:
        elapsed = max(0, int((now - t.discovered_at).total_seconds())) if t.discovered_at else 0
        current_age_seconds = max(0, int(t.age_seconds + elapsed))
        token_rows.append(
            {
                "symbol": t.symbol,
                "address": t.address,
                "fdv": t.fdv,
                "lp_usd": t.lp_usd,
                "lp_fdv_ratio": t.lp_fdv_ratio,
                "age_seconds": current_age_seconds,
            }
        )

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "formal": formal,
            "prelist": prelist,
            "tokens": token_rows,
            "events": events,
            "distribution": service.wallet_distribution(db),
            "now": now,
        },
    )


@app.post("/api/run/trending")
async def run_trending(db: Session = Depends(get_db)):
    await service.run_trending_pipeline(db)
    return JSONResponse({"ok": True})


@app.post("/api/run/daily")
async def run_daily(db: Session = Depends(get_db)):
    await service.run_daily_pipeline(db)
    return JSONResponse({"ok": True})


@app.get("/api/formal")
def api_formal(db: Session = Depends(get_db)):
    wallets = db.scalars(
        select(WalletCandidate)
        .where(WalletCandidate.formal_whitelist == 1)
        .order_by(desc(WalletCandidate.smart_score))
    ).all()
    return {
        "count": len(wallets),
        "items": [
            {
                "address": w.address,
                "score": w.smart_score,
                "grade": w.grade,
                "weight": w.weight,
                "status": w.status,
                "updated_at": w.updated_at.isoformat() if w.updated_at else None,
            }
            for w in wallets
        ],
    }
