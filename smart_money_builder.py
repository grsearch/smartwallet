from __future__ import annotations

import asyncio
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

import httpx


BIRDEYE_API_KEY = os.getenv("BIRDEYE_API_KEY", "").strip()
BIRDEYE_BASE_URL = os.getenv("BIRDEYE_BASE_URL", "https://public-api.birdeye.so")
BIRDEYE_CHAIN = os.getenv("BIRDEYE_CHAIN", "solana")

TOKEN_TOP_N = int(os.getenv("TOKEN_TOP_N", "20"))
TOKEN_MIN_AGE_HOURS = float(os.getenv("TOKEN_MIN_AGE_HOURS", "4"))
TOKEN_MAX_AGE_HOURS = float(os.getenv("TOKEN_MAX_AGE_HOURS", "168"))
TOKEN_MIN_FDV = float(os.getenv("TOKEN_MIN_FDV", "500000"))
TOKEN_MIN_LP_FDV_RATIO = float(os.getenv("TOKEN_MIN_LP_FDV_RATIO", "0.10"))

CANDIDATE_MAX_SIZE = int(os.getenv("CANDIDATE_MAX_SIZE", "150"))
FORMAL_MAX_SIZE = int(os.getenv("FORMAL_MAX_SIZE", "100"))

HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "20"))
HTTP_RETRIES = int(os.getenv("HTTP_RETRIES", "3"))
WALLET_CONCURRENCY = int(os.getenv("WALLET_CONCURRENCY", "3"))
GENERAL_CONCURRENCY = int(os.getenv("GENERAL_CONCURRENCY", "6"))


@dataclass
class TokenInfo:
    address: str
    symbol: str = ""
    name: str = ""
    fdv: float = 0.0
    liquidity_usd: float = 0.0
    lp_fdv_ratio: float = 0.0
    age_hours: float = 0.0
    creation_time: Optional[datetime] = None
    source: str = "birdeye_trending"
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class WalletScore:
    wallet_address: str
    smart_score: float
    profit_score: float
    repeat_score: float
    networth_score: float
    style_score: float
    activity_score: float
    entry_quality_score: float
    penalties: float
    grade: str
    weight: float
    pnl_30d: float
    win_rate: float
    avg_trade_pnl: float
    profit_loss_ratio: float
    net_worth: float
    tx_count_7d: int
    tx_count_30d: int
    last_active_at: Optional[str]
    appear_token_count: int
    notes: list[str] = field(default_factory=list)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_ts(ts: Any) -> Optional[datetime]:
    if ts is None:
        return None
    try:
        ts_int = int(ts)
        if ts_int > 10_000_000_000:
            ts_int /= 1000
        return datetime.fromtimestamp(ts_int, tz=timezone.utc)
    except Exception:
        return None


def calc_age_hours(created_at: Optional[datetime]) -> float:
    if not created_at:
        return 0.0
    return (utc_now() - created_at).total_seconds() / 3600


def normalize_grade(score: float) -> str:
    if score >= 80:
        return "A"
    if score >= 65:
        return "B"
    if score >= 50:
        return "C"
    return "D"


def normalize_weight(score: float) -> float:
    if score >= 85:
        return 1.0
    if score >= 75:
        return 0.7
    if score >= 65:
        return 0.4
    return 0.0


class BirdeyeClient:
    def __init__(self, api_key: str, chain: str = "solana") -> None:
        if not api_key:
            raise ValueError("BIRDEYE_API_KEY is required")
        self._client = httpx.AsyncClient(
            base_url=BIRDEYE_BASE_URL,
            timeout=HTTP_TIMEOUT,
            headers={
                "X-API-KEY": api_key,
                "x-chain": chain,
                "accept": "application/json",
                "content-type": "application/json",
            },
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, url: str, *, params: dict[str, Any] | None = None, json: dict[str, Any] | None = None) -> dict[str, Any]:
        last_exc: Exception | None = None
        for attempt in range(1, HTTP_RETRIES + 1):
            try:
                resp = await self._client.request(method, url, params=params, json=json)
                resp.raise_for_status()
                data = resp.json()
                return data if isinstance(data, dict) else {"success": True, "data": data}
            except Exception as exc:
                last_exc = exc
                if attempt < HTTP_RETRIES:
                    await asyncio.sleep(1.2 * attempt)
        raise RuntimeError(f"Birdeye request failed: {method} {url} error={last_exc}")

    async def get_trending_tokens(self, *, sort_by: str = "rank", sort_type: str = "desc", limit: int = 20) -> dict[str, Any]:
        return await self._request("GET", "/defi/token_trending", params={"sort_by": sort_by, "sort_type": sort_type, "offset": 0, "limit": limit})

    async def get_token_creation_info(self, token_address: str) -> dict[str, Any]:
        return await self._request("GET", "/defi/token_creation_info", params={"address": token_address})

    async def get_token_trades(self, token_address: str, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        return await self._request("GET", "/defi/txs/token", params={"address": token_address, "offset": offset, "limit": limit})

    async def get_smart_money_token_list(self, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        return await self._request("GET", "/smart-money/v1/token/list", params={"limit": limit, "offset": offset})

    async def get_wallet_pnl_multiple(self, wallets: list[str]) -> dict[str, Any]:
        return await self._request("GET", "/wallet/v2/pnl/multiple", params={"wallets": ",".join(wallets)})

    async def get_wallet_networth_summary_multiple(self, wallets: list[str]) -> dict[str, Any]:
        return await self._request("POST", "/wallet/v2/net-worth-summary/multiple", json={"wallets": wallets})

    async def get_wallet_tx_list(self, wallet: str, limit: int = 100, before: int | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {"wallet": wallet, "limit": limit}
        if before is not None:
            params["before"] = before
        return await self._request("GET", "/v1/wallet/tx_list", params=params)

    async def get_wallet_balance_change(self, wallet: str, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        return await self._request("GET", "/wallet/v2/balance-change", params={"wallet": wallet, "offset": offset, "limit": limit})


class TokenDiscoveryService:
    def __init__(self, client: BirdeyeClient) -> None:
        self.client = client
        self.sem = asyncio.Semaphore(GENERAL_CONCURRENCY)

    async def discover_target_tokens(self) -> list[TokenInfo]:
        trending = await self.client.get_trending_tokens(limit=TOKEN_TOP_N)
        tokens = [self._parse_trending_item(x) for x in extract_items(trending)]
        tokens = [t for t in tokens if t.address]
        enriched = await asyncio.gather(*(self._enrich_token_age(t) for t in tokens))
        return [t for t in enriched if self._is_target_token(t)]

    def _parse_trending_item(self, item: dict[str, Any]) -> TokenInfo:
        address = item.get("address") or item.get("token_address") or item.get("mint") or ""
        fdv = safe_float(item.get("fdv"))
        liquidity_usd = safe_float(item.get("liquidity")) or safe_float(item.get("liquidity_usd")) or safe_float((item.get("liquidity_info") or {}).get("usd"))
        return TokenInfo(
            address=address,
            symbol=item.get("symbol") or "",
            name=item.get("name") or "",
            fdv=fdv,
            liquidity_usd=liquidity_usd,
            lp_fdv_ratio=(liquidity_usd / fdv) if fdv > 0 else 0.0,
            raw=item,
        )

    async def _enrich_token_age(self, token: TokenInfo) -> TokenInfo:
        async with self.sem:
            try:
                item = extract_first_item(await self.client.get_token_creation_info(token.address))
                created_at = parse_ts(item.get("block_unix_time")) or parse_ts(item.get("blockTime")) or parse_ts(item.get("created_at")) or parse_ts(item.get("timestamp"))
                token.creation_time = created_at
                token.age_hours = calc_age_hours(created_at)
            except Exception:
                token.creation_time = None
                token.age_hours = 0.0
        return token

    def _is_target_token(self, token: TokenInfo) -> bool:
        return (
            token.age_hours > TOKEN_MIN_AGE_HOURS
            and token.age_hours < TOKEN_MAX_AGE_HOURS
            and token.fdv > TOKEN_MIN_FDV
            and token.lp_fdv_ratio > TOKEN_MIN_LP_FDV_RATIO
        )


class CandidateWalletDiscoveryService:
    def __init__(self, client: BirdeyeClient) -> None:
        self.client = client

    async def discover_candidate_wallets(self, tokens: list[TokenInfo]) -> dict[str, set[str]]:
        result: dict[str, set[str]] = {}
        smart_money_index = await self._build_smart_money_index()
        for token in tokens:
            wallets = set(smart_money_index.get(token.address, set()))
            if len(wallets) < 3:
                wallets |= await self._discover_wallets_from_token_trades(token.address)
            for wallet in wallets:
                result.setdefault(wallet, set()).add(token.address)
        return result

    async def _build_smart_money_index(self) -> dict[str, set[str]]:
        data = await self.client.get_smart_money_token_list(limit=100, offset=0)
        items = extract_items(data)
        index: dict[str, set[str]] = {}
        for item in items:
            token_address = item.get("address") or item.get("token_address") or item.get("mint") or ""
            if not token_address:
                continue
            possible_wallets: set[str] = set()
            for key in ("wallet", "wallet_address", "owner"):
                val = item.get(key)
                if isinstance(val, str) and val:
                    possible_wallets.add(val)
            for list_key in ("wallets", "traders", "smart_wallets"):
                arr = item.get(list_key)
                if isinstance(arr, list):
                    for x in arr:
                        if isinstance(x, str) and x:
                            possible_wallets.add(x)
                        elif isinstance(x, dict):
                            addr = x.get("wallet") or x.get("wallet_address") or x.get("owner")
                            if addr:
                                possible_wallets.add(addr)
            if possible_wallets:
                index.setdefault(token_address, set()).update(possible_wallets)
        return index

    async def _discover_wallets_from_token_trades(self, token_address: str) -> set[str]:
        items = extract_items(await self.client.get_token_trades(token_address, limit=80, offset=0))
        wallets: set[str] = set()
        for item in items:
            side = str(item.get("side", "")).lower()
            tx_type = str(item.get("txType", "")).lower()
            if side and side not in ("buy", "bid"):
                continue
            if tx_type and "buy" not in tx_type and side == "":
                continue
            for key in ("owner", "wallet", "maker", "from", "user"):
                addr = item.get(key)
                if isinstance(addr, str) and addr:
                    wallets.add(addr)
                    break
        return wallets


class WalletScoringService:
    def __init__(self, client: BirdeyeClient) -> None:
        self.client = client
        self.wallet_sem = asyncio.Semaphore(WALLET_CONCURRENCY)

    async def evaluate_wallets(self, wallet_token_map: dict[str, set[str]]) -> list[WalletScore]:
        wallets = list(wallet_token_map.keys())
        pnl_by_wallet = await self._fetch_pnl_map(wallets)
        networth_by_wallet = await self._fetch_networth_map(wallets)
        tasks = [self._evaluate_single_wallet(w, len(wallet_token_map.get(w, set())), pnl_by_wallet.get(w, {}), networth_by_wallet.get(w, {})) for w in wallets]
        scores = await asyncio.gather(*tasks)
        scores.sort(key=lambda x: x.smart_score, reverse=True)
        return scores

    async def _fetch_pnl_map(self, wallets: list[str]) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for chunk in chunked(wallets, 50):
            try:
                for item in extract_items(await self.client.get_wallet_pnl_multiple(chunk)):
                    wallet = item.get("wallet") or item.get("address")
                    if wallet:
                        result[wallet] = item
            except Exception:
                pass
        return result

    async def _fetch_networth_map(self, wallets: list[str]) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for chunk in chunked(wallets, 100):
            try:
                for item in extract_items(await self.client.get_wallet_networth_summary_multiple(chunk)):
                    wallet = item.get("wallet") or item.get("address")
                    if wallet:
                        result[wallet] = item
            except Exception:
                pass
        return result

    async def _evaluate_single_wallet(self, wallet: str, appear_token_count: int, pnl_data: dict[str, Any], networth_data: dict[str, Any]) -> WalletScore:
        async with self.wallet_sem:
            try:
                tx_data = await self.client.get_wallet_tx_list(wallet, limit=100)
            except Exception:
                tx_data = {}
            try:
                balance_change_data = await self.client.get_wallet_balance_change(wallet, limit=50)
            except Exception:
                balance_change_data = {}

        tx_items = extract_items(tx_data)
        balance_items = extract_items(balance_change_data)
        pnl_30d = extract_pnl_30d(pnl_data)
        win_rate = extract_win_rate(pnl_data)
        avg_trade_pnl = extract_avg_trade_pnl(pnl_data)
        profit_loss_ratio = extract_profit_loss_ratio(pnl_data)
        net_worth = extract_net_worth(networth_data)
        tx_count_7d, tx_count_30d, last_active_at = derive_activity_stats(tx_items)

        profit_score = calc_profit_score(pnl_30d, win_rate, avg_trade_pnl, profit_loss_ratio)
        repeat_score = calc_repeat_score(appear_token_count)
        networth_score = calc_networth_score(net_worth)
        style_score, style_notes = calc_style_score(tx_items, balance_items)
        activity_score, activity_notes = calc_activity_score(tx_count_7d, tx_count_30d, last_active_at)
        entry_quality_score = calc_entry_quality_score(tx_items)
        penalties, penalty_notes = calc_penalties(appear_token_count, tx_items, tx_count_7d, last_active_at)

        smart_score = max(0.0, min(100.0, 0.30 * profit_score + 0.20 * repeat_score + 0.10 * networth_score + 0.20 * style_score + 0.10 * activity_score + 0.10 * entry_quality_score - penalties))

        return WalletScore(
            wallet_address=wallet,
            smart_score=round(smart_score, 2),
            profit_score=round(profit_score, 2),
            repeat_score=round(repeat_score, 2),
            networth_score=round(networth_score, 2),
            style_score=round(style_score, 2),
            activity_score=round(activity_score, 2),
            entry_quality_score=round(entry_quality_score, 2),
            penalties=round(penalties, 2),
            grade=normalize_grade(smart_score),
            weight=normalize_weight(smart_score),
            pnl_30d=round(pnl_30d, 2),
            win_rate=round(win_rate, 2),
            avg_trade_pnl=round(avg_trade_pnl, 2),
            profit_loss_ratio=round(profit_loss_ratio, 2),
            net_worth=round(net_worth, 2),
            tx_count_7d=tx_count_7d,
            tx_count_30d=tx_count_30d,
            last_active_at=last_active_at.isoformat() if last_active_at else None,
            appear_token_count=appear_token_count,
            notes=[*style_notes, *activity_notes, *penalty_notes],
        )


def calc_profit_score(pnl_30d: float, win_rate: float, avg_trade_pnl: float, profit_loss_ratio: float) -> float:
    score = 0.0
    score += 10 if pnl_30d > 20000 else 8 if pnl_30d > 10000 else 6 if pnl_30d > 5000 else 4 if pnl_30d > 1000 else 2 if pnl_30d > 0 else 0
    score += 8 if win_rate >= 0.7 else 6 if win_rate >= 0.6 else 4 if win_rate >= 0.5 else 2 if win_rate >= 0.4 else 0
    score += 6 if avg_trade_pnl >= 1000 else 4 if avg_trade_pnl >= 300 else 2 if avg_trade_pnl > 0 else 0
    score += 6 if profit_loss_ratio >= 3 else 4 if profit_loss_ratio >= 2 else 2 if profit_loss_ratio >= 1.2 else 0
    return min(score, 30.0)


def calc_repeat_score(appear_token_count: int) -> float:
    return 20 if appear_token_count >= 8 else 16 if appear_token_count >= 6 else 12 if appear_token_count >= 4 else 8 if appear_token_count >= 3 else 4 if appear_token_count >= 2 else 1


def calc_networth_score(net_worth: float) -> float:
    return 10 if net_worth > 500000 else 9 if net_worth > 100000 else 7 if net_worth > 20000 else 4 if net_worth > 5000 else 2


def calc_style_score(tx_items: list[dict[str, Any]], balance_items: list[dict[str, Any]]) -> tuple[float, list[str]]:
    notes: list[str] = []
    score = 20.0
    if not tx_items:
        return 8.0, ["tx history missing"]
    timestamps = sorted([parse_ts(x.get("blockUnixTime") or x.get("block_unix_time") or x.get("timestamp")) for x in tx_items], key=lambda x: x or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    timestamps = [x for x in timestamps if x is not None]
    if len(tx_items) >= 80:
        score -= 6
        notes.append("high frequency tx volume")
    if len(timestamps) >= 10:
        short_gap_count = 0
        for i in range(len(timestamps) - 1):
            if abs((timestamps[i] - timestamps[i + 1]).total_seconds()) <= 60:
                short_gap_count += 1
        if short_gap_count >= 5:
            score -= 5
            notes.append("many very short tx gaps")
    if len(balance_items) >= 40:
        score -= 3
        notes.append("fragmented balance change pattern")
    return max(0.0, min(score, 20.0)), notes


def calc_activity_score(tx_count_7d: int, tx_count_30d: int, last_active_at: Optional[datetime]) -> tuple[float, list[str]]:
    notes: list[str] = []
    score = 0.0
    score += 4 if tx_count_7d > 0 else 0
    if tx_count_7d == 0:
        notes.append("inactive in last 7d")
    score += 6 if tx_count_30d >= 20 else 4 if tx_count_30d >= 5 else 2 if tx_count_30d > 0 else 0
    if tx_count_30d == 0:
        notes.append("inactive in last 30d")
    if last_active_at and calc_age_hours(last_active_at) > 24 * 14:
        notes.append("last active more than 14d ago")
    return min(score, 10.0), notes


def calc_entry_quality_score(tx_items: list[dict[str, Any]]) -> float:
    if not tx_items:
        return 3.0
    buy_count = 0
    for item in tx_items:
        side = str(item.get("side", "")).lower()
        tx_type = str(item.get("txType", "")).lower()
        if side in ("buy", "bid") or "buy" in tx_type:
            buy_count += 1
    return 7.0 if buy_count >= 20 else 6.0 if buy_count >= 8 else 5.0 if buy_count >= 3 else 4.0


def calc_penalties(appear_token_count: int, tx_items: list[dict[str, Any]], tx_count_7d: int, last_active_at: Optional[datetime]) -> tuple[float, list[str]]:
    penalty = 0.0
    notes: list[str] = []
    if appear_token_count <= 1:
        penalty += 15
        notes.append("only appeared once")
    if len(tx_items) >= 100:
        penalty += 10
        notes.append("possibly ultra high frequency")
    if tx_count_7d == 0:
        penalty += 15
        notes.append("inactive recently")
    if last_active_at and calc_age_hours(last_active_at) > 24 * 30:
        penalty += 10
        notes.append("inactive for over 30d")
    return penalty, notes


def extract_items(data: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        return []
    for key in ("data", "items", "result", "tokens", "wallets"):
        value = data.get(key)
        if isinstance(value, list):
            return [x for x in value if isinstance(x, dict)]
        if isinstance(value, dict):
            for subkey in ("items", "list", "tokens", "wallets"):
                sub = value.get(subkey)
                if isinstance(sub, list):
                    return [x for x in sub if isinstance(x, dict)]
    return []


def extract_first_item(data: dict[str, Any]) -> dict[str, Any]:
    items = extract_items(data)
    if items:
        return items[0]
    if isinstance(data.get("data"), dict):
        return data["data"]
    return {}


def extract_pnl_30d(item: dict[str, Any]) -> float:
    for key in ("pnl_30d", "realized_pnl_30d", "total_pnl_30d", "pnl"):
        if key in item:
            return safe_float(item.get(key))
    return 0.0


def extract_win_rate(item: dict[str, Any]) -> float:
    for key in ("win_rate", "winRate", "winning_ratio"):
        if key in item:
            val = safe_float(item.get(key))
            return val / 100.0 if val > 1 else val
    return 0.0


def extract_avg_trade_pnl(item: dict[str, Any]) -> float:
    for key in ("avg_trade_pnl", "avg_pnl", "avg_profit"):
        if key in item:
            return safe_float(item.get(key))
    return 0.0


def extract_profit_loss_ratio(item: dict[str, Any]) -> float:
    for key in ("profit_loss_ratio", "pl_ratio", "pnl_ratio"):
        if key in item:
            return safe_float(item.get(key))
    return 0.0


def extract_net_worth(item: dict[str, Any]) -> float:
    for key in ("net_worth", "netWorth", "usd_value", "value"):
        if key in item:
            return safe_float(item.get(key))
    return 0.0


def derive_activity_stats(tx_items: list[dict[str, Any]]) -> tuple[int, int, Optional[datetime]]:
    now = utc_now()
    tx_count_7d = 0
    tx_count_30d = 0
    last_active_at: Optional[datetime] = None
    for item in tx_items:
        ts = parse_ts(item.get("blockUnixTime") or item.get("block_unix_time") or item.get("timestamp"))
        if not ts:
            continue
        if last_active_at is None or ts > last_active_at:
            last_active_at = ts
        age_days = (now - ts).total_seconds() / 86400
        if age_days <= 30:
            tx_count_30d += 1
        if age_days <= 7:
            tx_count_7d += 1
    return tx_count_7d, tx_count_30d, last_active_at


class WhitelistBuilder:
    def __init__(self, client: BirdeyeClient) -> None:
        self.token_discovery = TokenDiscoveryService(client)
        self.wallet_discovery = CandidateWalletDiscoveryService(client)
        self.wallet_scoring = WalletScoringService(client)

    async def run_once(self) -> dict[str, Any]:
        tokens = await self.token_discovery.discover_target_tokens()
        wallet_token_map = await self.wallet_discovery.discover_candidate_wallets(tokens)
        scores = await self.wallet_scoring.evaluate_wallets(wallet_token_map)
        candidate_pool = scores[:CANDIDATE_MAX_SIZE]
        formal_pool = [
            x
            for x in candidate_pool[:FORMAL_MAX_SIZE]
            if x.smart_score >= 70 and x.repeat_score >= 4 and x.style_score >= 12 and x.activity_score >= 5
        ][:FORMAL_MAX_SIZE]
        return {
            "run_at": utc_now().isoformat(),
            "token_count": len(tokens),
            "wallet_count": len(scores),
            "tokens": [asdict(x) for x in tokens],
            "candidate_whitelist": [asdict(x) for x in candidate_pool],
            "formal_whitelist": [asdict(x) for x in formal_pool],
        }


def chunked(items: list[str], size: int) -> Iterable[list[str]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


async def main() -> None:
    client = BirdeyeClient(BIRDEYE_API_KEY, chain=BIRDEYE_CHAIN)
    try:
        result = await WhitelistBuilder(client).run_once()
        print("=" * 80)
        print("FORMAL WHITELIST")
        print("=" * 80)
        for idx, item in enumerate(result["formal_whitelist"], start=1):
            print(f"{idx:>3}. {item['wallet_address']} score={item['smart_score']} grade={item['grade']} weight={item['weight']} appear={item['appear_token_count']}")
        print()
        print(f"target tokens = {result['token_count']}")
        print(f"candidate wallets = {len(result['candidate_whitelist'])}")
        print(f"formal wallets = {len(result['formal_whitelist'])}")
    finally:
        await client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
