# SmartWallet

自动发现趋势代币并筛选 top traders，生成预存白名单（最多150）和正式白名单（最多100），并提供 dashboard 与 webhook 推送。

## 功能

- 每 15 分钟扫描 DexScreener trending 页面入口（`https://dexscreener.com/solana?rankBy=trendingScoreH24&order=desc`）前20
- 用 Birdeye 验证代币条件：
  - age: 4小时~7天
  - FDV > 500,000
  - LP/FDV > 10%
  - （当前版本暂不启用 LP Burned 过滤）
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


## AGE 与 FDV 数据策略

- AGE 来源优先级：`Birdeye.liquidityAddedAt`（优先）→ `DexScreener.pairCreatedAt` → `Birdeye.createdAt/createTime`。
- FDV 来源优先级：Birdeye `fdv/fdvUsd` + DexScreener token endpoint（不再直接信任 trending 页面快照字段）。
- 这样可避免部分代币出现 AGE 为空或 FDV 缺失时被误过滤。


## Top traders 采集说明

- 使用 Birdeye 官方接口：`/defi/v2/tokens/top_traders`。
- 解析多个可能的钱包字段（`owner/ownerAddress/wallet/walletAddress/maker/trader`）。
- 对地址做 Solana base58 格式校验，并二次检查钱包是否存在近期交易，过滤无交易记录地址。


## 过滤硬条件（已在管道中生效）

- AGE：`4小时 <= AGE <= 7天`
- FDV：`FDV > 500000`
- LP/FDV：`LP/FDV > 10%`

其中 AGE/FDV/LP 数据会通过 Birdeye + DexScreener token detail 聚合并刷新到目标代币记录。


## 预存白名单地址质量过滤

- Top traders 地址在进入候选池前会检查地址格式和近期交易记录。
- 钱包日评估阶段若无交易记录（txs 为空）会直接降为 D 并从候选池清理，不进入 Top150。


## 扫描失败原因排查

- 每次趋势扫描会写入 `trending_scan_summary` 系统事件，包含：候选总数、收录数量、各类过滤失败计数（AGE/FDV/LP-FDV/缺字段等）。
- 可在 dashboard 的系统事件区查看，快速定位“为什么看起来符合条件却未收录”。


## Top traders 候选地址进一步过滤

- 排除明显非钱包地址（如已知 token mint 地址、`pump` 结尾地址）。
- 候选地址需同时满足：有近期交易记录，且钱包 PnL/NetWorth 至少一个接口可返回有效数据。
