from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.config import settings


class BirdEyeClient:
    def __init__(self):
        self.base_url = settings.birdeye_base_url.rstrip("/")
        self.headers = {
            "X-API-KEY": settings.birdeye_api_key,
            "accept": "application/json",
            "x-chain": "solana",
        }

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        import httpx

        url = f"{self.base_url}{path}"
        async with httpx.AsyncClient(timeout=20) as client:
            res = await client.get(url, headers=self.headers, params=params)
            res.raise_for_status()
            return res.json()

    async def token_overview(self, token_address: str) -> dict[str, Any]:
        return await self._get("/defi/token_overview", {"address": token_address})

    async def token_top_traders(self, token_address: str, limit: int = 20) -> list[dict[str, Any]]:
        data = await self._get("/defi/v2/tokens/top_traders", {"address": token_address, "limit": limit})
        return data.get("data", {}).get("items", [])

    async def wallet_pnl(self, wallet_address: str) -> dict[str, Any]:
        return await self._get("/v1/wallet/pnl", {"wallet": wallet_address})

    async def wallet_net_worth(self, wallet_address: str) -> dict[str, Any]:
        return await self._get("/v1/wallet/net-worth", {"wallet": wallet_address})

    async def wallet_transactions(self, wallet_address: str, limit: int = 100) -> list[dict[str, Any]]:
        data = await self._get("/v1/wallet/tx_list", {"wallet": wallet_address, "limit": limit})
        return data.get("data", {}).get("items", [])

    @staticmethod
    def to_age_seconds(create_time: int | float) -> int:
        now = datetime.now(tz=timezone.utc).timestamp()
        ts = BirdEyeClient.normalize_unix_timestamp(create_time)
        return int(now - ts)

    @staticmethod
    def normalize_unix_timestamp(raw: int | float) -> float:
        """Normalize unix timestamps that may arrive in seconds/ms/us/ns."""
        ts = float(raw)
        # birdeye values can be ms/us in some datasets. reduce to seconds.
        while ts > 10_000_000_000:
            ts /= 1000.0
        return ts
