from __future__ import annotations

from typing import Any

import httpx


class DexScreenerClient:
    def __init__(self):
        self.url = "https://api.dexscreener.com/token-profiles/latest/v1"

    async def fetch_trending(self, limit: int = 20) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=20) as client:
            res = await client.get(self.url)
            res.raise_for_status()
            data = res.json()
        items = data if isinstance(data, list) else data.get("pairs", [])
        items = sorted(items, key=lambda x: x.get("boosts", {}).get("active", 0), reverse=True)
        return items[:limit]
