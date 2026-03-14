from __future__ import annotations


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(v, hi))


def score_profit_quality(pnl_30d: float, win_rate: float, avg_trade_pnl: float, profit_factor: float) -> float:
    pnl_s = clamp((pnl_30d / 10_000) * 100, 0, 100)
    win_s = clamp(win_rate * 100, 0, 100)
    avg_s = clamp((avg_trade_pnl / 200) * 100, 0, 100)
    pf_s = clamp((profit_factor / 3) * 100, 0, 100)
    return 0.34 * pnl_s + 0.26 * win_s + 0.20 * avg_s + 0.20 * pf_s


def score_repeat(hit_tokens: int, avg_rank: float) -> float:
    coverage_s = clamp((hit_tokens / 8) * 100, 0, 100)
    rank_s = clamp(((20 - avg_rank) / 19) * 100, 0, 100)
    return 0.5 * coverage_s + 0.5 * rank_s


def score_networth(networth: float) -> float:
    if networth <= 1000:
        return 10
    if networth <= 10_000:
        return 35
    if networth <= 100_000:
        return 70
    if networth <= 2_000_000:
        return 100
    return 80


def score_style(avg_hold_minutes: float, daily_trade_count: float, mev_like: bool) -> float:
    hold_s = 100 if avg_hold_minutes >= 60 else clamp((avg_hold_minutes / 60) * 100, 0, 100)
    freq_s = 100 if daily_trade_count <= 20 else clamp(100 - ((daily_trade_count - 20) / 80) * 100, 0, 100)
    mev_penalty = 40 if mev_like else 0
    return clamp(0.55 * hold_s + 0.45 * freq_s - mev_penalty, 0, 100)


def score_activity(active_7d: bool, active_30d: bool) -> float:
    return (40 if active_7d else 0) + (60 if active_30d else 0)


def score_entry_quality(early_entry_ratio: float) -> float:
    return clamp(early_entry_ratio * 100, 0, 100)


def compute_smart_score(
    profit_score: float,
    repeat_score: float,
    networth_score: float,
    style_score: float,
    activity_score: float,
    entry_quality_score: float,
    is_mev_like: bool,
    ultra_high_frequency: bool,
    only_appeared_once: bool,
    inactive_recently: bool,
    chase_buy_pattern: bool,
) -> float:
    base = (
        0.30 * profit_score
        + 0.20 * repeat_score
        + 0.10 * networth_score
        + 0.20 * style_score
        + 0.10 * activity_score
        + 0.10 * entry_quality_score
    )

    if is_mev_like:
        base -= 25
    if ultra_high_frequency:
        base -= 20
    if only_appeared_once:
        base -= 15
    if inactive_recently:
        base -= 15
    if chase_buy_pattern:
        base -= 10

    return clamp(base, 0, 100)


def grade_and_weight(smart_score: float) -> tuple[str, float]:
    if smart_score >= 85:
        return "A", 1.0
    if smart_score >= 75:
        return "A", 0.7
    if smart_score >= 65:
        return "B", 0.4
    if smart_score >= 50:
        return "C", 0.0
    return "D", 0.0
