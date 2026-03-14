# Smart Money Builder (Birdeye)

按你的新要求重写（并补上 Top PnL 网页抓取优先级）：

- 主入口：`/defi/token_trending`
- 代币年龄：`/defi/token_creation_info`
- 候选钱包发现优先级：
  1. Birdeye 网页 Token 页 `Top PnL`（Playwright 抓取）
  2. `GET /defi/v2/tokens/top_traders`
  3. `GET /smart-money/v1/token/list`
  4. 回退 `GET /defi/txs/token` 反推买入地址
- 钱包复评：`/wallet/v2/pnl/multiple`、`/v1/wallet/tx_list`、`/wallet/v2/balance-change`

## Quick Start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env
python smart_money_builder.py
```

## Notes

- 不在代码中硬编码 API key，统一从环境变量 `BIRDEYE_API_KEY` 读取。
- wallet multiple/batch 接口是否可用取决于套餐能力；骨架中默认容错并降级/跳过失败批次。
- CLI 会输出每个 token 的钱包发现诊断：
  - `smart_money_count`
  - `top_pnl_count`
  - `top_traders_count`
  - `final_wallet_count`
- 可通过 `USE_TOP_PNL_SCRAPER=0` 暂时关闭网页抓取路径。
