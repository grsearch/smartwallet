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

        return {
            "chainId": item.get("chainId") or item.get("chain") or "solana",
            "pairAddress": item.get("pairAddress") or item.get("address") or "",
            "tokenAddress": item.get("tokenAddress") or base.get("address") or item.get("address") or "",
            "symbol": item.get("symbol") or base.get("symbol") or "",
            "fdv": item.get("fdv") or 0,
            "liquidity": {
                "usd": liquidity.get("usd") if isinstance(liquidity, dict) else (item.get("liquidityUsd") or 0),
            },
        }
