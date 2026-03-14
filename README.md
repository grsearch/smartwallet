# SmartWallet

自动发现趋势代币并筛选 top traders，生成预存白名单（最多150）和正式白名单（最多100），并提供 dashboard 与 webhook 推送。

## 功能

- 每 15 分钟扫描 DexScreener trending 页面入口（`https://dexscreener.com/?rankBy=trendingScoreH24&order=desc`）前20
- 用 Birdeye 验证代币条件：
  - age: 4小时~7天
  - FDV > 500,000
  - LP/FDV > 10%
  - LP Burned = 100%
- 目标代币加入 7 天观察白名单，立即抓一次 top traders
- 每天继续抓 top traders，7天后自动移出代币白名单
- 钱包评分（100分制）并生成：
  - 预存白名单：Top 150
  - 正式白名单：Top 100（带硬过滤）
- 正式白名单变化时推送 webhook
- Dashboard 展示钱包、评分、代币与事件

## 快速开始

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
uvicorn app.main:app --reload
```

打开: http://127.0.0.1:8000

## 配置

`.env`:

```env
BIRDEYE_API_KEY=your_key
WEBHOOK_URL=
TRENDING_SCAN_MINUTES=15
```

## 手动触发任务

```bash
curl -X POST http://127.0.0.1:8000/api/run/trending
curl -X POST http://127.0.0.1:8000/api/run/daily
```


> 说明：趋势入口优先使用 DexScreener 页面（按 `trendingScoreH24` 排序）解析；若页面结构变更导致解析失败，才会回退到公开 API 作为兜底。
