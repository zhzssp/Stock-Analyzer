# Stock-Analyzer

基于麦蕊（mairuiapi.com）股票数据 API 复刻并扩展一套自选股分析表——包含现价、市值、财务指标，以及围绕**历史底部**展开的一系列派生指标（底/顶、离底%、顶底倍数、目标卖价等）。

当前已落地 **S1–S5 + S6 离线成份切片 + S7–S8.4（离线）**：本机登录、自选池、图 1 查询与导出、行情按指数成份查/导、analyst 多轮问答（DeepSeek / 粘贴表 / 仓库 / 带参接口）、researcher「看市场」、监控中心 + 本机总线/通知通道。期货/资讯/政策 Tool 已登记但未启用。S9 Electron 未做。默认 `MAIRUI_OFFLINE=1`。S0 正式 licence 与完整官方成份接口尚未用实盘跑通。

---

## 项目结构

```
Stock-Analyzer/
├── README.md                 # 本文件
├── docs/
│   ├── INDEX.md               # 文档入口：分类与权威
│   ├── 使用/                  # 部署教程、对客说明
│   ├── 设计/                  # 软件设计、智能体专论、API 现状
│   ├── 评审/                  # 提效缺口（默认不实现）
│   ├── 需求/                  # 客户原话（R-）
│   ├── 问题/                  # 已核实阻塞（P-）
│   ├── 报告/                  # 脚本生成，勿手改
│   └── frontend/              # 本机工作台（不要双击 HTML）
├── pics/                     # 现有表格截图，字段比对的基准
├── src/                      # FastAPI 单体（S1–S5）
├── tests/
├── requirements.txt
└── scripts/
    ├── setup.cmd             # 一键装 Python 到 E:\python-stock、建 venv
    ├── run-server.cmd        # 启动本机服务
    ├── Verify-Api.ps1        # 接口实测
    └── Verify-Index.ps1      # S0：指数成份探针
```

## 文档说明

文档分类和「听谁的」见 [`docs/INDEX.md`](docs/INDEX.md)。本文件只负责怎么跑、怎么验。

## 验证脚本

针对 [`docs/设计/API现状.md`](docs/设计/API现状.md) §4 逐条实测，避免只凭文档做设计。

```powershell
# 用你自己的正式 licence 运行（推荐）
.\scripts\Verify-Api.ps1 -Licence "你的licence"

# 附带限频压测（连续 40 次请求）
.\scripts\Verify-Api.ps1 -Licence "你的licence" -TestRateLimit

# 指定报告输出位置
.\scripts\Verify-Api.ps1 -Licence "你的licence" -OutFile ".\docs\报告\验证报告.md"
```

**环境要求：** Windows PowerShell 5.1 及以上，无需任何第三方依赖。

**测试项：**

| 编号 | 测试内容 |
|---|---|
| T0 | 连通性与 licence 有效性 |
| T0.5 | **数据源真实性探针（前置门禁）** |
| T1 | `hslt/list` 覆盖范围与 `dm` 字段真实格式 |
| T2 | 代码参数格式：带后缀 vs 纯 6 位 |
| T3+T4 | **历史回溯深度与单次条数上限（最关键）** |
| T5 | licence 是否需要「证书」前缀 |
| T6 | `ZygdSdgd` 对象的真实结构 |
| T7 | 补贴收入 `btsr` 与其他收益 `qtsy` |
| T8 | 「X 日价」指定日期取收盘价 |
| T9 | 科创板 / 北交所能否走 `hsstock` 历史接口 |
| T10 | 限频压测（默认跳过） |

### 关于 T0.5 前置门禁

脚本会先用**三个不同的股票代码**请求同一接口并比对返回值。若结果完全相同，说明当前 licence 只能拿到固定样本数据，此时所有依赖股票代码的测试项会被标记为 ⛔「无法验证」，而不会给出结论。

这个门禁不是多余的——首轮用官方公开演示 licence 实测时，`000001`、`600038`、`002230` 返回了**完全相同**的价格与市值，历史 K 线也恒为同一份 50 条平安银行数据且无视 `st`/`et` 参数。没有这道门禁，就会得出「API 只能回溯 1 年、17年后底不可行」的错误结论。

## 本机运行

完全不会用命令的，请按 [`docs/使用/本地部署教程.md`](docs/使用/本地部署教程.md) 做。下面是给已经会开终端的人看的精简步骤。

新机器（没有 `E:\python-stock` 下的 Python 3.11/3.12，或没有 `.venv`）先一键配置：

```bat
.\scripts\setup.cmd
```

解释器**必须**装在运行脚本那台机器的 `E:\python-stock`（例如 `E:\python-stock\python.exe`）。脚本只认这里的 3.11/3.12，不用系统 PATH 上的 3.9 或其他目录。找不到则下载官方 3.12.10 安装到该路径（需要有 `E:` 盘；权限不足时用管理员再跑一次）。然后建虚拟环境、装依赖、复制 `.env`。

然后启动：

```bat
.\scripts\run-server.cmd
```

没有 `.venv` 时，启动脚本会先跑 setup。若坚持用 PowerShell 且执行策略较严：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run-server.ps1
```

浏览器打开 http://127.0.0.1:8765 ，默认账号 `hanish` / `change-me`。离线模式即可进工作台，不必先填 licence。

可选：`.env` 里 `MAIRUI_OFFLINE=0` 并填写 `MAIRUI_LICENCE` 走正式行情；`LLM_API_KEY` 走 DeepSeek。演示 licence 仍会被门禁拒绝写入缓存。不填 key 时问答用确定性 Tool 编排，不编数字。

```powershell
.\.venv\Scripts\python.exe -m pytest
```

## 当前状态

**已完成**

- 74 个接口的字段盘点与表格需求比对
- 表头字段全部识别，确认不存在 API 覆盖不到的原始字段
- 文档缺陷排查：`ZygdSdgd` 未定义、5 处笔误、限频描述为无差别模板文本
- 实测确认：`hslt/list` 含科创板不含北交所（5203 只）、`dm` 实际带市场后缀、「证书」前缀确为笔误、`btsr` 已被 `qtsy` 取代

**待办**

- ⛔ **S0** 正式 licence 实测日线深度 **与** 指数成份接口（`scripts/Verify-Index.ps1`）
- **S6** 离线成份切片已可查/导；正式 licence 下用探针结果替换切片，不得用全市场冒充成份
- **S7 实盘调度**：离线规则已接；正式 licence 下需用真实行情/资金流/事件接口复核阈值

## 数据源

麦蕊数据 · https://api.mairuiapi.com

覆盖沪深 A 股、沪深指数、京市、科创板、基金。档位与限频见 [`docs/设计/API现状.md`](docs/设计/API现状.md) §4.2、§4.5。

> ⚠️ licence 属于凭据，请勿硬编码进代码或提交至版本库。建议通过环境变量传入：
>
> ```powershell
> $env:MAIRUI_LICENCE = "你的licence"
> .\scripts\Verify-Api.ps1 -Licence $env:MAIRUI_LICENCE
> ```
