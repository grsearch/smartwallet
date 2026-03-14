from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone

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
        skip_stats: dict[str, int] = defaultdict(int)

        for item in trending:
            chain = item.get("chainId", "")
            if chain not in ("solana", "sol"):
                skip_stats["non_solana"] += 1
                continue
            token_address = item.get("tokenAddress") or item.get("baseToken", {}).get("address")
            if not token_address:
                skip_stats["missing_token_address"] += 1
                continue

            dex_market = {}
            try:
                dex_market = await self.dex.fetch_token_market_data(token_address, item.get("pairAddress", ""))
            except Exception:
                dex_market = {}

            ov = await self.birdeye.token_overview(token_address)
            data = ov.get("data", {})
            age = self.resolve_age_seconds(data, dex_market)
            if age is None:
                skip_stats["missing_age_source"] += 1
                continue

            fdv = self.resolve_fdv(item, data, dex_market)
            liquidity = self.resolve_liquidity_usd(item, data, dex_market)
            lp_ratio = (liquidity / fdv) if fdv > 0 else 0
            lp_burned = float(data.get("lpBurnedPercent") or data.get("lp_burned_percent") or 0)

            if not (settings.min_age_seconds <= age <= settings.max_age_seconds):
                skip_stats["age_out_of_range"] += 1
                continue
            if fdv < settings.min_fdv:
                skip_stats["fdv_below_threshold"] += 1
                continue
            if lp_ratio < settings.min_lp_fdv_ratio:
                skip_stats["lp_fdv_below_threshold"] += 1
                continue
            # LP burned rule disabled per latest product instruction.

            existing = db.scalar(select(TokenWatch).where(TokenWatch.address == token_address))
            if existing:
                # refresh token metrics for dashboard / latest filtering visibility
                existing.symbol = item.get("symbol") or dex_market.get("symbol") or existing.symbol
                existing.pair_address = item.get("pairAddress", "") or dex_market.get("pairAddress", "")
                existing.fdv = fdv
                existing.lp_usd = liquidity
                existing.lp_fdv_ratio = lp_ratio
                existing.age_seconds = age
                existing.lp_burned_percent = lp_burned
                db.flush()
                skip_stats["already_watched_refreshed"] += 1
                continue

            tw = TokenWatch(
                chain="solana",
                address=token_address,
                symbol=(item.get("symbol") or dex_market.get("symbol") or item.get("baseToken", {}).get("symbol", "")),
                pair_address=item.get("pairAddress", "") or dex_market.get("pairAddress", ""),
                fdv=fdv,
                lp_usd=liquidity,
                lp_fdv_ratio=lp_ratio,
                age_seconds=age,
                lp_burned_percent=lp_burned,
                expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=settings.wallet_expiry_days),
            )
            db.add(tw)
            db.flush()
            inserted += 1
            await self.scan_top_traders_for_token(db, tw)

        summary_payload = {
            "event": "trending_scan_summary",
            "timestamp": datetime.utcnow().isoformat(),
            "total_candidates": len(trending),
            "inserted": inserted,
            "skip_stats": dict(skip_stats),
        }
        db.add(SystemEvent(event_type="trending_scan_summary", payload=json.dumps(summary_payload, ensure_ascii=False)))
        db.commit()
        return inserted

    def resolve_age_seconds(self, birdeye_data: dict, dex_market: dict) -> int | None:
        """Resolve AGE with ordered fallbacks:
        1) Birdeye liquidityAddedAt (LP-based age, preferred)
        2) DexScreener pairCreatedAt
        3) Birdeye createdAt/createTime
        """
        candidates = [
            birdeye_data.get("liquidityAddedAt"),
            dex_market.get("pairCreatedAt"),
            birdeye_data.get("createdAt"),
            birdeye_data.get("createTime"),
        ]
        for raw in candidates:
            if raw in (None, ""):
                continue
            try:
                return self.birdeye.to_age_seconds(float(raw))
            except Exception:
                continue
        return None

    @staticmethod
    def _as_float(value) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    def _first_numeric(self, *values) -> float:
        for value in values:
            n = self._as_float(value)
            if n > 0:
                return n
        return 0.0

    def resolve_fdv(self, item: dict, birdeye_data: dict, dex_market: dict) -> float:
        birdeye_fdv = self._first_numeric(
            birdeye_data.get("fdv"),
            birdeye_data.get("fdvUsd"),
            birdeye_data.get("fullyDilutedValuation"),
            birdeye_data.get("marketCap"),
            (birdeye_data.get("market") or {}).get("fdv"),
            (birdeye_data.get("market") or {}).get("fdvUsd"),
        )
        dex_fdv = self._first_numeric(item.get("fdv"), dex_market.get("fdv"))
        return max(dex_fdv, birdeye_fdv)

    def resolve_liquidity_usd(self, item: dict, birdeye_data: dict, dex_market: dict) -> float:
        birdeye_liq = self._first_numeric(
            birdeye_data.get("liquidityUsd"),
            birdeye_data.get("liquidity"),
            (birdeye_data.get("liquidity") or {}).get("usd") if isinstance(birdeye_data.get("liquidity"), dict) else 0,
            (birdeye_data.get("market") or {}).get("liquidityUsd"),
        )
        dex_liq = self._first_numeric(
            (item.get("liquidity") or {}).get("usd"),
            (dex_market.get("liquidity") or {}).get("usd"),
        )
        return max(dex_liq, birdeye_liq)

    async def scan_top_traders_for_token(self, db: Session, token: TokenWatch):
        items = await self.birdeye.token_top_traders(token.address, limit=20)
        for idx, row in enumerate(items, start=1):
            wallet = self.extract_wallet_address(row)
            if not wallet or not self.is_valid_solana_wallet(wallet):
                continue

            # Ignore program-like/no-history addresses that are not tradable wallets.
            if not await self.wallet_has_recent_transactions(wallet):
                continue

            hit = WalletTopTraderHit(wallet_address=wallet, token_address=token.address, rank=idx)
            db.add(hit)

            wc = db.scalar(select(WalletCandidate).where(WalletCandidate.address == wallet))
            if wc is None:
                wc = WalletCandidate(address=wallet)
                db.add(wc)

        token.last_top_trader_scan_at = datetime.utcnow()
        db.flush()

    @staticmethod
    def extract_wallet_address(row: dict) -> str:
        candidates = [
            row.get("owner"),
            row.get("ownerAddress"),
            row.get("wallet"),
            row.get("walletAddress"),
            row.get("maker"),
            row.get("trader"),
            row.get("address"),
        ]
        for c in candidates:
            if isinstance(c, str) and c:
                return c
        return ""

    @staticmethod
    def is_valid_solana_wallet(address: str) -> bool:
        # base58-like, 32~44 chars
        return bool(re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{32,44}", address))

    async def wallet_has_recent_transactions(self, wallet: str) -> bool:
        try:
            txs = await self.birdeye.wallet_transactions(wallet, limit=5)
            return len(txs) > 0
        except Exception:
            return False

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

        if not txs:
            wallet.smart_score = 0
            wallet.grade = "D"
            wallet.weight = 0
            wallet.status = "drop"
            wallet.formal_whitelist = 0
            wallet.active_7d = 0
            wallet.active_30d = 0
            wallet.daily_trade_count = 0
            wallet.updated_at = datetime.utcnow()
            return

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
            last_dt = datetime.fromtimestamp(latest, tz=timezone.utc)
            wallet.active_7d = int((datetime.now(timezone.utc) - last_dt).days <= 7)
            wallet.active_30d = int((datetime.now(timezone.utc) - last_dt).days <= 30)
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

        # hard prune wallets with no transaction footprint
        for w in ranked:
            if w.daily_trade_count <= 0:
                db.delete(w)
        db.flush()
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
