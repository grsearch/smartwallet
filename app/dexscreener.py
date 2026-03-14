from __future__ import annotations

import json
import re
from typing import Any

import httpx


class DexScreenerClient:
    """DexScreener trending source.

    Primary source: website entry requested by product spec
    https://dexscreener.com/?rankBy=trendingScoreH24&order=desc

    We parse page bootstrap JSON and extract pair/token rows in the same ordering.
    If parsing fails, fallback to public token-profile API to keep pipeline alive.
    """

    def __init__(self):
        self.trending_entry_url = "https://dexscreener.com/?rankBy=trendingScoreH24&order=desc"
        self.fallback_api_url = "https://api.dexscreener.com/token-profiles/latest/v1"
        self.token_pairs_url = "https://api.dexscreener.com/latest/dex/tokens/{token}"

    async def fetch_trending(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = await self._fetch_from_trending_page(limit)
        if rows:
            return rows[:limit]

        # Fallback only: keep service available even if page schema changes.
        return await self._fetch_from_fallback_api(limit)

    async def _fetch_from_trending_page(self, limit: int) -> list[dict[str, Any]]:
        html = await self._http_get_text(self.trending_entry_url)
        if not html:
            return []

        next_data = self._extract_next_data(html)
        if not next_data:
            return []

        candidates = self._collect_possible_rows(next_data)
        normalized = [self._normalize_item(x) for x in candidates]
        normalized = [x for x in normalized if x.get("tokenAddress")]

        # page is already ordered by trendingScoreH24 desc, keep order and dedupe by token
        dedup: dict[str, dict[str, Any]] = {}
        for item in normalized:
            token = item["tokenAddress"]
            if token not in dedup:
                dedup[token] = item
            if len(dedup) >= limit:
                break

        return list(dedup.values())

    async def _fetch_from_fallback_api(self, limit: int) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=20) as client:
            res = await client.get(self.fallback_api_url)
            res.raise_for_status()
            data = res.json()

        items = data if isinstance(data, list) else data.get("pairs", [])
        items = sorted(items, key=lambda x: x.get("boosts", {}).get("active", 0), reverse=True)
        return [self._normalize_item(x) for x in items[:limit]]

    async def fetch_token_market_data(self, token_address: str, preferred_pair_address: str = "") -> dict[str, Any]:
        """Fetch token pair details from DexScreener token endpoint.

        Used as fallback/complement for AGE (pairCreatedAt) and FDV/liquidity fields.
        """
        url = self.token_pairs_url.format(token=token_address)
        async with httpx.AsyncClient(timeout=20) as client:
            res = await client.get(url)
            res.raise_for_status()
            payload = res.json()

        pairs = payload.get("pairs") if isinstance(payload, dict) else None
        if not pairs:
            return {}

        sol_pairs = [p for p in pairs if str(p.get("chainId", "")).lower() in {"solana", "sol"}]
        if not sol_pairs:
            return {}

        if preferred_pair_address:
            for p in sol_pairs:
                if (p.get("pairAddress") or "").lower() == preferred_pair_address.lower():
                    return self._normalize_item(p)

        # fallback to the most liquid pair
        best = max(sol_pairs, key=lambda p: float((p.get("liquidity") or {}).get("usd") or 0))
        return self._normalize_item(best)

    async def _http_get_text(self, url: str) -> str:
        async with httpx.AsyncClient(timeout=20) as client:
            res = await client.get(url)
            res.raise_for_status()
            return res.text

    @staticmethod
    def _extract_next_data(html: str) -> dict[str, Any] | None:
        m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.S)
        if not m:
            return None
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            return None

    def _collect_possible_rows(self, obj: Any) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []

        def walk(node: Any):
            if isinstance(node, dict):
                if self._looks_like_pair_row(node):
                    out.append(node)
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for x in node:
                    walk(x)

        walk(obj)
        return out

    @staticmethod
    def _looks_like_pair_row(node: dict[str, Any]) -> bool:
        chain = str(node.get("chainId") or node.get("chain") or "").lower()
        addr = node.get("pairAddress") or node.get("tokenAddress") or node.get("address")
        has_token = bool(node.get("baseToken") or node.get("token") or node.get("symbol"))
        return bool(addr and has_token and chain in {"sol", "solana"})

    @staticmethod
    def _normalize_item(item: dict[str, Any]) -> dict[str, Any]:
        base = item.get("baseToken") or item.get("token") or {}
        liquidity = item.get("liquidity") or {}

        fdv = (
            item.get("fdv")
            or item.get("fullyDilutedValuation")
            or item.get("marketCap")
            or item.get("fdvUsd")
            or 0
        )
        pair_created_at = item.get("pairCreatedAt") or item.get("createdAt") or 0

        return {
            "chainId": item.get("chainId") or item.get("chain") or "solana",
            "pairAddress": item.get("pairAddress") or item.get("address") or "",
            "tokenAddress": item.get("tokenAddress") or base.get("address") or item.get("address") or "",
            "symbol": item.get("symbol") or base.get("symbol") or "",
            "fdv": float(fdv or 0),
            "liquidity": {
                "usd": liquidity.get("usd") if isinstance(liquidity, dict) else (item.get("liquidityUsd") or 0),
            },
            "pairCreatedAt": pair_created_at,
        }
