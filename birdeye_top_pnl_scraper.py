from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class TopPnlWalletRow:
    wallet_address: str
    wallet_label: str
    wallet_age_label: str
    sol_balance: Optional[float]
    token_balance_usd: Optional[float]
    position_usd: Optional[float]
    total_pnl_usd: Optional[float]
    total_pnl_pct: Optional[float]
    realized_pnl_usd: Optional[float]
    realized_pnl_pct: Optional[float]


def parse_money_to_float(text: str) -> Optional[float]:
    if not text:
        return None
    s = text.strip().replace(",", "").replace("$", "").replace("+", "")
    multiplier = 1.0
    if s.endswith("K"):
        multiplier = 1_000
        s = s[:-1]
    elif s.endswith("M"):
        multiplier = 1_000_000
        s = s[:-1]
    elif s.endswith("B"):
        multiplier = 1_000_000_000
        s = s[:-1]
    try:
        return float(s) * multiplier
    except ValueError:
        return None


def parse_pct(text: str) -> Optional[float]:
    if not text:
        return None
    s = text.strip().replace(",", "").replace("%", "").replace("+", "")
    try:
        return float(s)
    except ValueError:
        return None


def looks_like_solana_address(text: str) -> bool:
    return bool(re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{32,44}", text.strip()))


class BirdeyeTopPnlScraper:
    def __init__(self, headless: bool = True) -> None:
        self.headless = headless

    async def scrape_token_top_pnl(self, token_address: str, *, chain: str = "solana", timeout_ms: int = 30000) -> list[TopPnlWalletRow]:
        # lazy import: script can run without playwright installed unless this feature is used
        from playwright.async_api import async_playwright

        url = f"https://birdeye.so/token/{token_address}?chain={chain}"
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=self.headless)
            page = await browser.new_page(viewport={"width": 1600, "height": 1200})
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                await self._try_click_text(page, "Top PnL")
                await page.wait_for_timeout(2500)
                return await self._extract_rows(page)
            finally:
                await browser.close()

    async def _try_click_text(self, page, text: str) -> None:
        candidates = [page.get_by_text(text, exact=True), page.locator(f"text={text}")]
        for locator in candidates:
            try:
                await locator.first.click(timeout=5000)
                return
            except Exception:
                continue

    async def _extract_rows(self, page) -> list[TopPnlWalletRow]:
        rows_out: list[TopPnlWalletRow] = []
        row_locators = page.locator("tr")
        row_count = await row_locators.count()

        for i in range(row_count):
            row = row_locators.nth(i)
            texts = await row.locator("td").all_inner_texts()
            if not texts:
                continue

            joined = " | ".join(t.strip() for t in texts if t.strip())
            if not joined:
                continue

            wallet_address = ""
            wallet_label = ""

            links = row.locator("a")
            link_count = await links.count()
            for j in range(link_count):
                txt = (await links.nth(j).inner_text()).strip()
                if looks_like_solana_address(txt):
                    wallet_address = txt
                    break
                if txt and not wallet_label:
                    wallet_label = txt

            if not wallet_address:
                possible = re.findall(r"[1-9A-HJ-NP-Za-km-z]{32,44}", joined)
                if possible:
                    wallet_address = possible[0]

            if not wallet_address:
                continue

            wallet_age_label = ""
            age_match = re.search(r"\b(\d+[smhdw]o?)\b", joined)
            if age_match:
                wallet_age_label = age_match.group(1)

            total_pnl_usd = None
            total_pnl_pct = None
            realized_pnl_usd = None
            realized_pnl_pct = None
            sol_balance = None
            token_balance_usd = None
            position_usd = None

            cols = [t.strip() for t in texts if t.strip()]
            if len(cols) >= 6:
                sol_balance = parse_money_to_float(cols[1].replace("◎", "").strip())
                token_balance_usd = parse_money_to_float(cols[2])
                position_usd = parse_money_to_float(cols[3])

                total_parts = cols[4].splitlines()
                if total_parts:
                    total_pnl_usd = parse_money_to_float(total_parts[0])
                if len(total_parts) > 1:
                    total_pnl_pct = parse_pct(total_parts[1])

                realized_parts = cols[5].splitlines()
                if realized_parts:
                    realized_pnl_usd = parse_money_to_float(realized_parts[0])
                if len(realized_parts) > 1:
                    realized_pnl_pct = parse_pct(realized_parts[1])

            rows_out.append(
                TopPnlWalletRow(
                    wallet_address=wallet_address,
                    wallet_label=wallet_label or wallet_address,
                    wallet_age_label=wallet_age_label,
                    sol_balance=sol_balance,
                    token_balance_usd=token_balance_usd,
                    position_usd=position_usd,
                    total_pnl_usd=total_pnl_usd,
                    total_pnl_pct=total_pnl_pct,
                    realized_pnl_usd=realized_pnl_usd,
                    realized_pnl_pct=realized_pnl_pct,
                )
            )

        dedup = {row.wallet_address: row for row in rows_out}
        return list(dedup.values())
