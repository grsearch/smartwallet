from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TokenWatch(Base):
    __tablename__ = "token_watch"

    id: Mapped[int] = mapped_column(primary_key=True)
    chain: Mapped[str] = mapped_column(String(32), default="solana")
    address: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    symbol: Mapped[str] = mapped_column(String(32), default="")
    pair_address: Mapped[str] = mapped_column(String(128), default="")
    fdv: Mapped[float] = mapped_column(Float, default=0)
    lp_usd: Mapped[float] = mapped_column(Float, default=0)
    lp_fdv_ratio: Mapped[float] = mapped_column(Float, default=0)
    age_seconds: Mapped[int] = mapped_column(Integer, default=0)
    lp_burned_percent: Mapped[float] = mapped_column(Float, default=0)
    discovered_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    last_top_trader_scan_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class WalletCandidate(Base):
    __tablename__ = "wallet_candidate"

    id: Mapped[int] = mapped_column(primary_key=True)
    address: Mapped[str] = mapped_column(String(128), unique=True, index=True)

    smart_score: Mapped[float] = mapped_column(Float, default=0)
    grade: Mapped[str] = mapped_column(String(2), default="D")
    weight: Mapped[float] = mapped_column(Float, default=0)

    profit_score: Mapped[float] = mapped_column(Float, default=0)
    repeat_score: Mapped[float] = mapped_column(Float, default=0)
    networth_score: Mapped[float] = mapped_column(Float, default=0)
    style_score: Mapped[float] = mapped_column(Float, default=0)
    activity_score: Mapped[float] = mapped_column(Float, default=0)
    entry_quality_score: Mapped[float] = mapped_column(Float, default=0)

    repeat_hits: Mapped[int] = mapped_column(Integer, default=0)
    token_coverage: Mapped[int] = mapped_column(Integer, default=0)
    pnl_30d: Mapped[float] = mapped_column(Float, default=0)
    win_rate: Mapped[float] = mapped_column(Float, default=0)
    avg_trade_pnl: Mapped[float] = mapped_column(Float, default=0)
    profit_factor: Mapped[float] = mapped_column(Float, default=0)
    net_worth: Mapped[float] = mapped_column(Float, default=0)
    avg_hold_minutes: Mapped[float] = mapped_column(Float, default=0)
    daily_trade_count: Mapped[float] = mapped_column(Float, default=0)
    mev_like: Mapped[int] = mapped_column(Integer, default=0)
    active_7d: Mapped[int] = mapped_column(Integer, default=0)
    active_30d: Mapped[int] = mapped_column(Integer, default=0)

    formal_whitelist: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="prelist")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class WalletTopTraderHit(Base):
    __tablename__ = "wallet_top_trader_hit"

    id: Mapped[int] = mapped_column(primary_key=True)
    wallet_address: Mapped[str] = mapped_column(String(128), index=True)
    token_address: Mapped[str] = mapped_column(String(128), index=True)
    rank: Mapped[int] = mapped_column(Integer, default=999)
    captured_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class SystemEvent(Base):
    __tablename__ = "system_event"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
