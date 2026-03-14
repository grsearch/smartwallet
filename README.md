# Smart Money Builder (Birdeye)

按你的新要求重写：

- 主入口：`/defi/token_trending`
- 代币年龄：`/defi/token_creation_info`
- smart money 线索优先：`/smart-money/v1/token/list`
- 钱包复评：`/wallet/v2/pnl/multiple`、`/v1/wallet/tx_list`、`/wallet/v2/balance-change`
- 回退：当 smart money token list 无法直接提钱包时，回退 `/defi/txs/token` 反推买入地址

## Quick Start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python smart_money_builder.py
```

## Notes

- 不在代码中硬编码 API key，统一从环境变量 `BIRDEYE_API_KEY` 读取。
- wallet multiple/batch 接口是否可用取决于套餐能力；骨架中默认容错并降级/跳过失败批次。
- 这是可扩展骨架，便于继续补 PostgreSQL、APScheduler、FastAPI Dashboard。
