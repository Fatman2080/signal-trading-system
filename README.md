# 策略信号交易系统 v1.1

通用型量化策略 **多信号源 + 多账号** 加密货币交易执行系统。

采集多个信号源 → 加权聚合 → 策略引擎生成订单 → 风控过滤（持仓感知）→ 按权重分配到多账号执行 → 自动挂止盈止损 → 持仓同步与交易复盘。

---

## 系统架构

```
┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐
│  PA+MACD    │  │ Alpha Factor│  │ Inline Code │  │  Webhook    │   ← 可插拔信号源
│  (pa_macd)  │  │(alpha_factor│  │(inline_code)│  │  (外部推送) │
└──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘
       │                │                │                │
       └────────────────┼────────────────┼────────────────┘
                        ▼
              ┌───────────────────┐
              │   信号聚合器       │   ← 加权聚合 + min_strength 过滤
              │  SignalAggregator │     继承最强信号的 SL/TP/reasons
              └────────┬──────────┘
                       ▼
              ┌───────────────────┐
              │   策略引擎         │   ← 信号 → PendingOrder（含 SL/TP）
              │  StrategyEngine   │
              └────────┬──────────┘
                       ▼
              ┌───────────────────┐
              │   风控过滤         │   ← 白名单 + 仓位感知 + 反向平仓
              │  OrderValidator   │     持仓同步（自动检测交易所平仓）
              └────────┬──────────┘
                       ▼
              ┌───────────────────┐
              │  多账号执行器      │   ← 下单 + 自动挂 TP/SL 条件单
              │  MultiAccountExec │
              └──┬─────┬─────┬───┘
                 ▼     ▼     ▼
              Hyperliquid  币安合约  模拟盘
```

---

## 目录结构

```
多信号交易看板/
├── app.py                          # Web 后端入口（Flask，端口 8888）
├── requirements.txt                # Python 依赖
│
├── config/                         # 配置文件（YAML）
│   ├── accounts.yaml               #   交易账号（API Key / 私钥）⚠️ 不入 Git
│   ├── accounts.yaml.example       #   账号配置模板
│   ├── signals.yaml                #   信号源配置（类型、周期、权重）
│   ├── strategy.yaml               #   交易策略（标的白名单、下单方式）
│   ├── risk.yaml                   #   风控配置（止盈止损、仓位限制）
│   ├── risk.yaml.example           #   风控配置模板
│   ├── webhook.yaml                #   Webhook 密钥 ⚠️ 不入 Git
│   └── webhook.yaml.example        #   Webhook 配置模板
│
├── strategies/                     # 策略库（配置模板）
│   ├── pa_macd.yaml                #   PA+MACD 策略配置示例
│   ├── alpha_factor.yaml           #   Alpha 因子策略配置示例
│   └── webhook.yaml                #   Webhook 信号源配置示例
│
├── src/                            # 后端核心逻辑
│   ├── main.py                     #   主流程：信号→聚合→策略→风控→执行
│   ├── scheduler.py                #   定时调度器（后台线程周期执行）
│   ├── config_io.py                #   配置文件读写工具
│   ├── log_store.py                #   持久化运行日志
│   │
│   ├── signals/                    #   信号层
│   │   ├── base.py                 #     TradingSignal 数据模型
│   │   ├── aggregator.py           #     多信号加权聚合（继承 extra）
│   │   ├── queue.py                #     Webhook 信号队列
│   │   └── sources/                #     信号源目录（可插拔）
│   │       ├── registry.py         #       @register_source 装饰器
│   │       ├── pa_macd.py          #       PA+MACD 组合信号（K线形态+MACD+背离）
│   │       ├── alpha_factor.py     #       Alpha 因子信号（z-score）
│   │       ├── inline_code.py      #       内联代码信号（YAML 中嵌入策略）
│   │       └── webhook.py          #       Webhook 外部推送信号
│   │
│   ├── strategy/                   #   策略层
│   │   └── engine.py               #     信号 → PendingOrder（传递 SL/TP）
│   │
│   ├── risk/                       #   风控层
│   │   └── order_validate.py       #     白名单 + 仓位感知 + 反向平仓 + 限额
│   │
│   ├── execution/                  #   执行层
│   │   ├── order_types.py          #     PendingOrder 数据模型（含 SL/TP）
│   │   ├── account_manager.py      #     多账号管理
│   │   ├── executor.py             #     多账号执行器 + 自动挂 TP/SL
│   │   └── brokers/                #     经纪商适配器
│   │       ├── base.py             #       抽象基类 BrokerBase
│   │       ├── hyperliquid_broker.py #     Hyperliquid 永续合约
│   │       ├── binance_futures.py  #       币安合约（框架）
│   │       └── sim.py              #       模拟盘
│   │
│   └── journal/                    #   交易日志
│       └── trade_log.py            #     开平仓记录 + 持仓同步 + 复盘统计
│
├── data/                           # 运行时数据（不入 Git）
│   ├── trades.jsonl                #   交易记录
│   └── run_logs.jsonl              #   持久化运行日志
│
└── web/                            # Web 前端（终端风格 UI）
    ├── index.html                  #   主页面
    └── static/
        ├── css/style.css           #   样式（暗黑终端主题）
        └── js/app.js               #   前端逻辑
```

---

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置账号

复制模板并填入你的 API 信息：

```bash
cp config/accounts.yaml.example config/accounts.yaml
```

**Hyperliquid 账号示例：**

```yaml
accounts:
  - id: hype_01
    name: Hyperliquid 主账号
    broker: hyperliquid
    weight: 1.0
    enabled: true
    api_key: "0x你的钱包地址"
    api_secret: "你的私钥（hex）"
    testnet: false
```

### 3. 配置风控

```bash
cp config/risk.yaml.example config/risk.yaml
```

### 4. 启动

```bash
python app.py
# 浏览器打开 http://localhost:8888
```

---

## 配置说明

### 信号源（config/signals.yaml）

```yaml
sources:
  - id: pa_btc
    type: pa_macd          # PA+MACD 策略
    symbol: BTC
    interval: 1h           # K线周期
    limit: 250             # K线数量
    weight: 1              # 聚合权重
    account_id: hype_01    # 指定执行账号（留空=按权重分配）

aggregator:
  min_strength: 0.3        # 聚合后低于此强度的信号被过滤
```

### 交易策略（config/strategy.yaml）

```yaml
strategy:
  symbols:                 # 允许交易的币种白名单
    - BTC
    - SOL
    - ETH
  default_order_type: market
  quantity_per_signal: 0.5 # 每信号基础下单量（乘以信号强度）
```

### 风控配置（config/risk.yaml）

```yaml
dry_run: false             # true=模拟运行，不实际下单

reverse_close: true        # 反向信号时自动平仓
allow_add_position: false  # 同方向是否允许加仓

tp_sl:
  enabled: true            # 开仓后自动挂止盈止损条件单
  default_sl_pct: 0.02     # 默认止损 2%（信号自带 SL 时优先用信号的）
  default_tp_pct: 0.03     # 默认止盈 3%
  use_signal_levels: true  # 优先使用信号源计算的 SL/TP

max_single_order_pct: 0.5  # 单笔占账户权益上限 50%
max_position_pct: 0.2      # 单币种仓位上限 20%
max_total_exposure_pct: 3.0
max_daily_trades: 100
```

---

## 内置信号源

| 类型 | 注册名 | 说明 |
|------|--------|------|
| PA+MACD | `pa_macd` | K线形态（吞没/锤子）+ MACD 金叉死叉 + 背离 + EMA200 趋势 + 成交量，自动计算 SL/TP |
| Alpha 因子 | `alpha_factor` | 基于预定义因子库的 z-score 信号 |
| 内联代码 | `inline_code` | 在 YAML 中直接嵌入 Python 策略代码 |
| Webhook | `webhook` | 接收外部系统推送的 JSON 信号 |

---

## 核心功能

### 止盈止损

- 开仓成交后**自动向交易所挂 TP/SL 条件单**（Trigger Order）
- 交易所端监控执行，系统离线也能触发
- PA+MACD 策略自动计算 Swing ± ATR 止损/止盈
- 无信号级 SL/TP 时，按 `risk.yaml` 百分比填充默认值
- 看板持仓表格实时显示止损/止盈价格

### 持仓同步

- 每次交易周期和刷新持仓时，自动对比交易所实际持仓与日志记录
- 如果某仓位已被 TP/SL 条件单平掉，系统**自动补录平仓记录**
- 确保复盘统计数据始终准确

### 风控（持仓感知）

- 已有同向持仓时**跳过重复开仓**
- 收到反向信号时**自动先平仓再开仓**
- 单笔/单币种/总敞口三级仓位限制
- 每日交易笔数上限
- 币种白名单（大小写不敏感）

### 交易复盘

- 每笔开平仓持久化记录到 `data/trades.jsonl`
- 平仓自动关联对应的开仓记录
- 看板实时展示：胜率、总盈亏、最佳/最差交易

---

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET  | `/api/config` | 获取全部配置 |
| POST | `/api/config` | 保存全部配置 |
| POST | `/api/run` | 手动执行一次交易周期 |
| GET  | `/api/positions` | 查询持仓 + 余额 + TP/SL 挂单 |
| GET  | `/api/trades` | 交易历史记录与复盘统计 |
| POST | `/api/webhook` | 接收外部信号推送 |
| GET  | `/api/logs` | 获取持久化运行日志 |
| POST | `/api/logs/clear` | 清空运行日志 |
| GET  | `/api/scheduler/status` | 调度器状态 |
| POST | `/api/scheduler/start` | 启动定时调度器 |
| POST | `/api/scheduler/stop` | 停止调度器 |
| GET  | `/api/webhook/status` | Webhook 队列状态 |
| POST | `/api/webhook/generate-secret` | 生成 Webhook 密钥 |
| POST | `/api/signal/test` | 测试信号源 |
| GET  | `/api/factors` | 获取可用因子列表 |

---

## 接入自定义信号源

在 `src/signals/sources/` 下新建 `.py` 文件：

```python
from ..base import TradingSignal, SignalDirection
from .registry import register_source

@register_source("my_strategy")
class MySource:
    def __init__(self, source_id, account_id=None, symbol="BTC", interval="1h", **kwargs):
        self.source_id = source_id
        self.account_id = account_id
        self.symbol = symbol

    def fetch_signals(self) -> list[TradingSignal]:
        # 实现你的信号逻辑，返回 TradingSignal 列表
        return [TradingSignal(
            symbol=self.symbol,
            direction=SignalDirection.LONG,
            strength=0.8,
            source=self.source_id,
            account_id=self.account_id,
            extra={
                "stop_loss": 68000,      # 可选：自定义止损价
                "take_profit_1": 75000,  # 可选：自定义止盈价
                "reasons": ["金叉", "放量"],
            },
        )]
```

然后在 `config/signals.yaml` 中添加配置即可使用。

---

## Web 界面

终端/黑客风格仪表盘：

- **运行日志**：实时彩色日志（系统/策略/风控/信号源/执行器）
- **仪表盘**：风控状态、信号源、策略、执行器、分配器、Webhook 队列、调度器
- **持仓面板**：实时持仓 + 止损/止盈价格 + 未实现盈亏
- **交易复盘**：胜率、总盈亏、历史交易记录
- **配置面板**：内联编辑账号/信号源/策略/风控参数
- **调度器控制**：启动/停止自动交易周期
