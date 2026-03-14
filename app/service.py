from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.birdeye import BirdEyeClient
from app.config import settings
from app.dexscreener import DexScreenerClient
from app.models import SystemEvent, TokenWatch, WalletCandidate, WalletTopTraderHit
from app.scoring import (
    compute_smart_score,
    grade_and_weight,
    score_activity,
    score_entry_quality,
    score_networth,
    score_profit_quality,
    score_repeat,
    score_style,
)


class SmartWalletService:
    def __init__(self):
        self.dex = DexScreenerClient()
        self.birdeye = BirdEyeClient()

    async def scan_trending_tokens(self, db: Session) -> int:
        trending = await self.dex.fetch_trending(settings.top_trending_limit)
        inserted = 0

        for item in trending:
            chain = item.get("chainId", "")
            if chain not in ("solana", "sol"):
                continue
            token_address = item.get("tokenAddress") or item.get("baseToken", {}).get("address")
            if not token_address:
                continue

            ov = await self.birdeye.token_overview(token_address)
            data = ov.get("data", {})
            create_time = data.get("createTime")
            if not create_time:
                continue

            age = self.birdeye.to_age_seconds(create_time)
            fdv = float(item.get("fdv") or data.get("fdv") or 0)
            liquidity = float(item.get("liquidity", {}).get("usd") or data.get("liquidity") or 0)
            lp_ratio = (liquidity / fdv) if fdv > 0 else 0
            lp_burned = float(data.get("lpBurnedPercent") or data.get("lp_burned_percent") or 0)

            if not (settings.min_age_seconds <= age <= settings.max_age_seconds):
                continue
            if fdv < settings.min_fdv:
                continue
            if lp_ratio < settings.min_lp_fdv_ratio:
                continue
            if lp_burned < 100:
                continue

            existing = db.scalar(select(TokenWatch).where(TokenWatch.address == token_address))
            if existing:
                continue

            tw = TokenWatch(
                chain="solana",
                address=token_address,
                symbol=item.get("symbol") or item.get("baseToken", {}).get("symbol", ""),
                pair_address=item.get("pairAddress", ""),
                fdv=fdv,
                lp_usd=liquidity,
                lp_fdv_ratio=lp_ratio,
                age_seconds=age,
                lp_burned_percent=lp_burned,
                expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=settings.wallet_expiry_days),
            )
            db.add(tw)
            db.flush()
            inserted += 1
            await self.scan_top_traders_for_token(db, tw)

        db.commit()
        return inserted

    async def scan_top_traders_for_token(self, db: Session, token: TokenWatch):
        items = await self.birdeye.token_top_traders(token.address, limit=20)
        for idx, row in enumerate(items, start=1):
            wallet = row.get("owner") or row.get("wallet") or row.get("address")
            if not wallet:
                continue
            hit = WalletTopTraderHit(wallet_address=wallet, token_address=token.address, rank=idx)
            db.add(hit)

            wc = db.scalar(select(WalletCandidate).where(WalletCandidate.address == wallet))
            if wc is None:
                wc = WalletCandidate(address=wallet)
                db.add(wc)

        token.last_top_trader_scan_at = datetime.utcnow()
        db.flush()

    async def scan_token_whitelist_daily(self, db: Session):
        now = datetime.utcnow()
        tokens = db.scalars(select(TokenWatch).where(TokenWatch.expires_at >= now)).all()
        for tk in tokens:
            await self.scan_top_traders_for_token(db, tk)

        expired = db.scalars(select(TokenWatch).where(TokenWatch.expires_at < now)).all()
        for tk in expired:
            db.delete(tk)
        db.commit()

    async def evaluate_wallet(self, db: Session, wallet: WalletCandidate):
        pnl = await self.birdeye.wallet_pnl(wallet.address)
        net = await self.birdeye.wallet_net_worth(wallet.address)
        txs = await self.birdeye.wallet_transactions(wallet.address, limit=100)

        pnl_data = pnl.get("data", {})
        wallet.pnl_30d = float(pnl_data.get("pnl30d") or pnl_data.get("realizedPnl30d") or 0)
        wallet.win_rate = float(pnl_data.get("winRate") or 0)
        wallet.avg_trade_pnl = float(pnl_data.get("avgTradePnl") or 0)
        wallet.profit_factor = float(pnl_data.get("profitFactor") or 0)

        wallet.net_worth = float(net.get("data", {}).get("netWorth") or 0)

        parsed_holds = [float(x.get("holdMinutes", 0)) for x in txs if x.get("holdMinutes") is not None]
        wallet.avg_hold_minutes = sum(parsed_holds) / len(parsed_holds) if parsed_holds else 0
        wallet.daily_trade_count = len(txs) / 7

        times = [x.get("blockTime") for x in txs if x.get("blockTime")]
        if times:
            latest = max(times)
            last_dt = datetime.fromtimestamp(latest, tz=UTC)
            wallet.active_7d = int((datetime.now(UTC) - last_dt).days <= 7)
            wallet.active_30d = int((datetime.now(UTC) - last_dt).days <= 30)
        else:
            wallet.active_7d = 0
            wallet.active_30d = 0

        wallet.mev_like = int(wallet.daily_trade_count > 80 and wallet.avg_hold_minutes < 2)

        hits = db.scalars(select(WalletTopTraderHit).where(WalletTopTraderHit.wallet_address == wallet.address)).all()
        token_set = {h.token_address for h in hits}
        wallet.repeat_hits = len(hits)
        wallet.token_coverage = len(token_set)
        avg_rank = (sum(h.rank for h in hits) / len(hits)) if hits else 20

        early_entries = [x for x in txs if float(x.get("priceImpactPct", 100)) < 2.5]
        early_entry_ratio = len(early_entries) / len(txs) if txs else 0

        wallet.profit_score = score_profit_quality(wallet.pnl_30d, wallet.win_rate, wallet.avg_trade_pnl, wallet.profit_factor)
        wallet.repeat_score = score_repeat(wallet.token_coverage, avg_rank)
        wallet.networth_score = score_networth(wallet.net_worth)
        wallet.style_score = score_style(wallet.avg_hold_minutes, wallet.daily_trade_count, bool(wallet.mev_like))
        wallet.activity_score = score_activity(bool(wallet.active_7d), bool(wallet.active_30d))
        wallet.entry_quality_score = score_entry_quality(early_entry_ratio)

        score = compute_smart_score(
            profit_score=wallet.profit_score,
            repeat_score=wallet.repeat_score,
            networth_score=wallet.networth_score,
            style_score=wallet.style_score,
            activity_score=wallet.activity_score,
            entry_quality_score=wallet.entry_quality_score,
            is_mev_like=bool(wallet.mev_like),
            ultra_high_frequency=wallet.daily_trade_count > 150,
            only_appeared_once=wallet.token_coverage <= 1,
            inactive_recently=not bool(wallet.active_7d),
            chase_buy_pattern=early_entry_ratio < 0.25,
        )
        wallet.smart_score = score
        wallet.grade, wallet.weight = grade_and_weight(score)
        wallet.updated_at = datetime.utcnow()

        if score >= 80 and wallet.active_7d and not wallet.mev_like:
            wallet.status = "core"
        elif score >= 65:
            wallet.status = "watch"
        elif score >= 50:
            wallet.status = "candidate"
        else:
            wallet.status = "drop"

    async def evaluate_all_wallets(self, db: Session):
        wallets = db.scalars(select(WalletCandidate).all()).all()
        for w in wallets:
            try:
                await self.evaluate_wallet(db, w)
            except Exception:
                continue

        ranked = db.scalars(select(WalletCandidate).order_by(desc(WalletCandidate.smart_score))).all()
        top_150 = ranked[: settings.max_prelist_wallets]

        allowed_150 = {w.address for w in top_150}
        for w in ranked:
            if w.address not in allowed_150:
                db.delete(w)

        formal_top = [
            w
            for w in top_150
            if w.smart_score >= 70 and w.repeat_score >= 50 and w.style_score >= 60 and w.activity_score >= 50
        ][: settings.formal_whitelist_limit]

        old_formal = {w.address for w in ranked if w.formal_whitelist}
        new_formal = {w.address for w in formal_top}

        for w in top_150:
            w.formal_whitelist = 1 if w.address in new_formal else 0

        if old_formal != new_formal:
            await self.send_whitelist_update(db, sorted(list(new_formal)))

        db.commit()

    async def send_whitelist_update(self, db: Session, wallets: list[str]):
        payload = {
            "event": "formal_whitelist_updated",
            "timestamp": datetime.utcnow().isoformat(),
            "count": len(wallets),
            "wallets": wallets,
        }
        db.add(SystemEvent(event_type="formal_whitelist_updated", payload=json.dumps(payload, ensure_ascii=False)))

        if settings.webhook_url:
            async with httpx.AsyncClient(timeout=20) as client:
                try:
                    await client.post(settings.webhook_url, json=payload)
                except Exception:
                    pass
        db.flush()

    async def run_trending_pipeline(self, db: Session):
        await self.scan_trending_tokens(db)
        await self.evaluate_all_wallets(db)

    async def run_daily_pipeline(self, db: Session):
        await self.scan_token_whitelist_daily(db)
        await self.evaluate_all_wallets(db)

    def wallet_distribution(self, db: Session) -> dict[str, int]:
        out = defaultdict(int)
        wallets = db.scalars(select(WalletCandidate)).all()
        for w in wallets:
            out[w.grade] += 1
        return dict(out)
