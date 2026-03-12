# 策略信号交易系统 v1.0

通用型量化策略 **多信号 + 多账号** 交易执行系统。

采集多个信号源 → 加权聚合 → 策略引擎生成订单 → 风控过滤 → 按权重分配到多账号执行。支持为某个信号源指定固定执行账号。

---

## 系统架构

```
┌─────────────┐  ┌─────────────┐  ┌─────────────┐
│  信号源 A    │  │  信号源 B    │  │  信号源 C    │   ← 可插拔，@register_source 注册
│  (dummy)    │  │  (custom)   │  │  (macd)     │
└──────┬──────┘  └──────┬──────┘  └──────┬──────┘
       │                │                │
       └────────────────┼────────────────┘
                        ▼
              ┌───────────────────┐
              │   信号聚合器       │   ← 加权聚合 + min_strength 过滤
              │  SignalAggregator │
              └────────┬──────────┘
                       ▼
              ┌───────────────────┐
              │   策略引擎         │   ← 信号 → PendingOrder
              │  StrategyEngine   │
              └────────┬──────────┘
                       ▼
              ┌───────────────────┐
              │   风控过滤         │   ← 标的白名单 + 单笔比例限制
              │  OrderValidator   │
              └────────┬──────────┘
                       ▼
              ┌───────────────────┐
              │  多账号执行器      │   ← 指定账号 或 按权重分配
              │  MultiAccountExec │
              └──┬─────┬─────┬───┘
                 ▼     ▼     ▼
              账号1  账号2  账号3     ← SimBroker / CTP / 自定义
```

---

## 目录结构

```
策略信号交易系统1.0/
├── app.py                          # Web 后端入口（Flask，端口 8888）
├── gui.py                          # 桌面图形界面入口（Tkinter）
├── run.py                          # 命令行运行入口
├── requirements.txt                # Python 依赖
│
├── config/                         # 配置文件（YAML）
│   ├── accounts.yaml               #   交易账号（ID、经纪商、权重、API Key）
│   ├── signals.yaml                #   信号源（类型、权重、执行账号）
│   └── strategy.yaml               #   策略参数与风控参数
│
├── src/                            # 后端核心逻辑
│   ├── main.py                     #   主流程：信号→聚合→策略→风控→执行
│   ├── config_io.py                #   配置文件读写工具
│   │
│   ├── signals/                    #   信号层
│   │   ├── base.py                 #     TradingSignal 数据模型
│   │   ├── aggregator.py           #     多信号加权聚合
│   │   └── sources/                #     信号源目录（可插拔）
│   │       ├── registry.py         #       注册表：@register_source 装饰器
│   │       ├── dummy.py            #       模拟信号源（内置）
│   │       └── custom_example.py   #       自定义信号源模板
│   │
│   ├── strategy/                   #   策略层
│   │   └── engine.py               #     信号 → 订单转换
│   │
│   ├── risk/                       #   风控层
│   │   └── order_validate.py       #     标的白名单 + 比例过滤
│   │
│   └── execution/                  #   执行层
│       ├── order_types.py          #     PendingOrder 数据模型
│       ├── account_manager.py      #     多账号管理（API Key + 环境变量）
│       ├── executor.py             #     多账号执行器（按权重/指定账号）
│       └── brokers/                #     经纪商适配器
│           ├── base.py             #       抽象基类 BrokerBase
│           └── sim.py              #       模拟经纪商（打印不下单）
│
└── web/                            # Web 前端（终端风格 UI）
    ├── index.html                  #   主页面
    └── static/
        ├── css/style.css           #   样式（暗黑终端主题）
        └── js/app.js               #   前端逻辑
```

---

## 快速开始

### 安装依赖

```bash
cd 策略信号交易系统1.0
pip install -r requirements.txt
```

### 启动方式

**Web 界面（推荐）**

```bash
python app.py
# 浏览器打开 http://localhost:8888
```

**桌面 GUI**

```bash
python gui.py
```

**仅命令行执行**

```bash
python run.py
```

---

## 配置说明

### 账号配置（config/accounts.yaml）

```yaml
accounts:
  - id: account_1
    name: 主账户
    broker: sim           # sim=模拟盘，可扩展 ctp 等
    weight: 0.5           # 权重分配比例
    enabled: true
    api_key: ""           # 支持直接填写或 ${ENV_VAR} 环境变量
    api_secret: ""
```

### 信号源配置（config/signals.yaml）

```yaml
sources:
  - id: momentum
    type: dummy           # 信号源类型，对应 @register_source("dummy")
    weight: 0.6           # 聚合权重
    account_id: null      # null=按权重分配，填账号ID=固定该账号执行

aggregator:
  min_strength: 0.3       # 聚合后强度低于此值的信号被过滤
```

### 策略与风控（config/strategy.yaml）

```yaml
strategy:
  symbols: ["600519.SH"]  # 允许交易的标的白名单
  default_order_type: limit
  max_position_pct: 0.2   # 单标的最大仓位占比

risk:
  max_single_order_pct: 0.1
  max_daily_trades: 100
  dry_run: false          # true=试运行，只打印不下单
```

---

## 接入自定义信号源

只需 **3 步**，无需修改任何已有代码：

### 第 1 步：创建信号源文件

在 `src/signals/sources/` 下新建 `.py` 文件：

```python
# src/signals/sources/my_strategy.py
from typing import Optional
from ..base import TradingSignal, SignalDirection
from .registry import register_source

@register_source("my_strategy")
class MyStrategySource:
    def __init__(self, source_id, account_id=None, **kwargs):
        self.source_id = source_id
        self.account_id = account_id

    def fetch_signals(self) -> list[TradingSignal]:
        # 在这里实现你的信号逻辑
        return [
            TradingSignal(
                symbol="600519.SH",
                direction=SignalDirection.LONG,
                strength=0.8,
                source=self.source_id,
                account_id=self.account_id,
            )
        ]
```

### 第 2 步：配置信号源

在 `config/signals.yaml` 中添加：

```yaml
sources:
  - id: my_signal
    type: my_strategy     # 对应 @register_source("my_strategy")
    weight: 0.7
    account_id: null
```

### 第 3 步：运行

```bash
python run.py   # 或启动 Web 界面点击运行
```

系统自动扫描 `src/signals/sources/` 下所有模块并注册。

---

## Web 界面说明

终端/黑客风格仪表盘，左右分栏布局：

- **左侧 — 运行日志**：实时显示系统各模块的执行日志，带彩色标签区分（系统/策略/风控/信号源/执行器/分配器）
- **右侧 — 仪表盘**：顶部统计栏 + 5 个模块面板（风控、信号源、策略、执行器、分配器）
- **[ 配置 ]**：弹出配置面板，内联编辑账号/信号源/策略参数
- **[ 运行 ]**：保存配置并执行一次完整交易周期
- **[ 保存 ]**：仅保存配置不执行

---

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET  | `/api/config` | 获取全部配置 |
| POST | `/api/config` | 保存全部配置（JSON body） |
| POST | `/api/run`    | 执行一次交易周期，返回订单列表 |

---

## 核心数据流

```
TradingSignal（信号）
  ├── symbol:     标的代码
  ├── direction:  LONG / SHORT / NEUTRAL
  ├── strength:   信号强度 0~1
  ├── source:     来源标识
  └── account_id: 指定执行账号（null=按权重分配）

      ↓ 聚合后

PendingOrder（待执行订单）
  ├── symbol, side, quantity, order_type, price
  ├── signal_strength
  └── account_id: 继承自信号

      ↓ 风控过滤后

  MultiAccountExecutor.execute_orders()
  ├── 有 account_id → 仅该账号下单
  └── 无 account_id → 按权重分配到所有启用账号
```

---

## 开发计划

### 近期（v1.1）

- [ ] **接入真实经纪商**：实现 CTP / 券商 API 的 Broker 适配器，对接真实交易通道
- [ ] **定时调度**：添加定时器 / Cron 机制，支持自动周期性执行（如每分钟、每5分钟、每日定时）
- [ ] **信号源扩展**：内置常用信号源（Webhook 接收器、REST API 轮询、WebSocket 推送）
- [ ] **持久化日志**：运行日志写入文件 / 数据库，前端支持历史日志查看

### 中期（v1.5）

- [ ] **订单管理**：订单状态追踪（已提交/已成交/已撤销），支持撤单操作
- [ ] **持仓管理**：实时查询各账号持仓，仪表盘展示持仓分布
- [ ] **收益统计**：记录每笔交易盈亏，生成收益曲线图
- [ ] **多策略引擎**：支持配置多个独立策略，各策略独立风控与账号分配
- [ ] **回测框架**：基于历史数据回测策略表现，输出回测报告

### 远期（v2.0）

- [ ] **实时行情接入**：对接行情源（CTP行情、聚宽、Tushare 等），策略引擎基于实时数据决策
- [ ] **Web 端增强**：K线图、持仓分布图、收益曲线可视化
- [ ] **告警通知**：异常订单/风控触发时通过邮件、微信、钉钉推送告警
- [ ] **多用户与权限**：Web 端登录认证，不同用户管理各自的策略与账号
- [ ] **容器化部署**：Docker 打包 + docker-compose 一键部署
