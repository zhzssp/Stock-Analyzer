# Agent 缺陷核实与完善方案

> 核实日期：2026-09-29　｜　方式：**逐条读代码**，未发起任何数据请求、未消耗证书次数
> 本文是 `占位与半成品现状.md` 与 `R-20260921-未完成能力欠账.md` 的补充：那两份记的是"哪些能力没做"，
> 本文记的是"**已经做了但做得不对**"的部分（真缺陷 + 文档与代码矛盾）。

## 0. 实施进度

| 期 | 状态 | 验证 |
|---|---|---|
| **S1 止血** | ✅ **已实施（2026-09-29）** | 见下 |
| S2 可用 | 未开工 | — |
| S3 正确 | 未开工 | — |
| S4 接线 | 未开工（依赖 S3 的 loader 修复） | — |

**S1 三项的落地与验证**

1. **P0-1 工具走缓存**：新增 `market_cache_mode`（`src/tools/base.py`），在 `registry.run` 统一包一层；watcher 逐只规则调用点同包一层（`watcher.py:332`）。开关 `settings.agent_tool_cache_default`（默认开）。
   - 实盘验证：同一问法连跑两次 `company_profile` → 第 1 次 `misses=1`，第 2 次 `hits=1`（**0 请求**），且 `query_refresh_mode` 每次都还原为 `full`。
2. **P0-2 涨跌停池缓存**：`limit_pool_codes` 加独立 TTL（`settings.limit_pool_ttl_sec = 300`），**取空不缓存**（避免一次网络抖动把"今天没有涨停"这个假结论缓存住）。不走 `_slow_load`（那条只服务慢字段）。
3. **P0-3 调度健壮性**：per-user `try/except` + 复盘/配额清理独立兜底 + 出错写 `data/logs/scheduler.log`；三个 job 加 `misfire_grace_time` / `coalesce` / `max_instances`；启动时若今天（交易日）没跑过日终则延迟 20 秒补跑（标记文件 `data/last_eod.json`）。

回归测试：`tests/test_agent_s1_offline.py`（6 条）——工具进入/还原 cache、工具抛异常也还原、池缓存命中、空结果不缓存、eod 标记往返、日志不抛异常。全量 **157 passed**。

遗留：`监控与麦蕊额度预算.md` 里"股东/基金 24h 内 ≈0"的账目，在 P0-1 之后才成立（此前逐只规则跑在 full 模式，与账目不符）。

---

## 1. 核实结论总览

| 编号 | 问题 | 核实结果 | 级别 |
|---|---|---|---|
| A13 | Agent 问答与 watcher 逐只规则不走缓存 | ✅ 属实（`market_tools.py` 全文无 `refresh_mode`） | **P0** |
| A14 | 涨跌停池无缓存，盘中每 5 分钟各打 1 次 | ✅ 属实 | **P0** |
| A1 | 调度 `_tick` 无异常隔离，一处异常拖垮整轮 | ✅ 属实（`scheduler.py:36-46`） | **P0** |
| A2 | 20:20 错过即永久丢失，无补跑 | ✅ 属实（`add_job` 未设 `misfire_grace_time`） | **P0** |
| D4 | LLM 返回空 `tool_calls` 时不回退启发式 | ✅ 属实（`planner.py:344`） | **P0** |
| D5 | `tool_choice` 恒 `auto`，无强制取数重试 | ✅ 属实（`llm.py:68`，全仓仅定义+使用 2 处） | **P0** |
| D2 | manifest 恒挂空壳函数，开开关必失败 | ✅ 属实（`loader.py:47`） | **P1** |
| D3 | `/agent/tools/reload` 对工具是空操作 | ✅ 属实（`loader.py:45-46`） | **P1** |
| D1 | `futures_quote`(yaml) 与 `futures_map`(代码) id 不一致 | ✅ 属实 | **P1** |
| D8 | 流式会话在断连时整轮丢失 | ✅ 属实（`routes.py:1289` 在循环之后） | **P1** |
| D9 | SSE 无 error 事件、无整轮超时 | ✅ 属实 | **P1** |
| A5 | 提醒档位 `as_of` 不落库 | ✅ 属实（`models.py:133-152` 无该列） | **P1** |
| A6 | 资讯/政策不写快照 → 隔天重复提醒 | ✅ 属实（`_rule_web_sources` 全程无 `_write_snap`） | **P1** |
| A7 | 非交易日仍会白打涨跌停池 2 次 | ✅ 属实（拉池 `:350-351` 在跳过判断 `:359` 之前） | **P1** |
| A8 | 自定义规则校验失败被静默吞掉 | ✅ 属实（`watcher.py:307-310`） | **P1** |
| A10 | `watch.reviewed` 事件无任何订阅者 | ✅ 属实（`channels.py:50-52` 只订阅 3 个） | **P1** |
| A11 | 复盘只捞 `pending/deferred` | ✅ 属实（`reviewer.py:234-239`） | **P1** |
| D10 | `always_tools` / `forbidden` 声明了但不执行 | ✅ 属实（全仓仅在 `policy.py` 内出现） | **P2** |
| A3 | `start_scheduler` 导入失败静默返回 None | ✅ 属实（`scheduler.py:8-12`） | **P2** |
| A4 | 调度器持有 `market` 旧引用 | ✅ 属实（`scheduler.py:16` 函数内 import 绑定） | **P2** |
| D11 | `fund_holding` / `export_share` yaml 是死配置 | ✅ 属实 | **P2** |
| D12 | 会话标题取原文 128 字；找不到会话就静默新建 | ✅ 属实（`routes.py:1243/1250`） | **P2** |
| — | `watcher.py` 全文无 `futures` 分支 | ✅ 属实（U1 占位，即使开启也不跑） | 设计如此 |

### 需要订正的文档（文档与代码矛盾）

| 位置 | 现有说法 | 代码实际 | 处理 |
|---|---|---|---|
| `R-20260921` §2 U4（2026-09-23 核对写入） | `_alert()` **没有**按天/按 job 的去重查询 | **有**：`_today_dup`（`watcher.py:138-150`），调用点 `:194`，条件 `created_at >= 今日 0 点` 且仅 `persist=True` 时生效 | 已订正 |
| `占位与半成品现状` §2.2 U4 | 去重靠"快照指纹 + URL" | news/policy **没有指纹**，只有按天去重 + 单轮内 URL 去重 | 已订正 |
| `监控与麦蕊额度预算` 股东/基金 24h 内 ≈0 | 缓存会命中 | 逐只规则跑在 `full` 模式，缓存**写了但读不到** | 待订正（随 A13 一并改） |

---

## 1. P0：直接烧钱 / 直接让功能不可用

### P0-1　Agent 与 watcher 逐只规则不走缓存（A13）

**现象**：缓存一直在写，却很少被读。

- 闸门：`client.py:234-236` —— `_slow_load` 要求 `mode == "cache"` 才读缓存
- 但 `_slow_store`（`:246-249`）**不看 mode，照写不误**
- 结果：Agent 每问一次基本面/财务/股东就直连一次麦蕊

**证据**：`src/tools/market_tools.py:53/75/95`（`company_profile` / `holders_flow` / `finance_snapshot`）全文无 `refresh_mode`；
`watcher.py:562/587/605/625/650/676` 逐只规则直接 `ctx.market.*`，此时 `query_refresh_mode` 已被 `QueryEngine.run` 还原为默认 `"full"`。

**影响**：这是此前**证书额度打满的主要推手之一**。文档里"24h 内 ≈0"的账与代码不符。

**修复方案**（在上下文层统一，不逐个工具改）：
1. `ToolContext` 增加 `market_cache()` 上下文管理器：进入时置 `market.query_refresh_mode = "cache"`，退出还原。
2. `registry.run()`（工具执行入口）默认包一层；用户显式点"全量更新 / 强制实时"的链路（`/query/run` 的 `force_live=true`）**不包**。
3. watcher 逐只规则：在 `_finish_watcher` 内包一层（与既有 `:248-256` 的 `_profile_cached` 同思路）。

**验收**：离线模式下跑一次问答 + 一次 watcher 日终，断言 `market.slow_cache_stats["hits"] > 0`；同一问答连问两次，第二次请求数为 0。

**工作量**：小　**风险**：中（需确认"实时价"不被缓存污染——缓存 TTL 与快刷口径要一致）

### P0-2　涨跌停池无缓存（A14）

**证据**：`watcher.py:350-351` 每轮无条件 `market.limit_pool_codes("up"/"down")` → `client.py` 走 `_try_get`，无 slow cache。

**修复**：给 `limit_pool_codes` 加 slow cache，TTL 建议 **300 秒**（盘中 5 分钟轮询正好复用）；非交易时段可放大。

**验收**：连续两轮 session tick，池接口只打 1 次。

**工作量**：小

### P0-3　调度无异常隔离 + 错过不补（A1 / A2）

**证据**：
```36:46:src/platform/scheduler.py
    def _tick(schedule=None):
        db = SessionLocal()
        try:
            for user in db.query(User).all():
                run_watcher(db, user, market, schedule=schedule)
                if schedule == "eod":
                    run_reviewer(db, user, market)
            if schedule == "eod":
                enforce_all(db)
        finally:
            db.close()
```
- 无 per-user `try/except` → 一个用户额度耗尽抛 `LicenceExhaustedError` → 后续用户 + 复盘 + 配额清理全不执行
- `add_job` 未传 `misfire_grace_time` / `coalesce` / `max_instances`（APScheduler 默认 `misfire_grace_time=1s`）

**修复**：
1. 循环体加 per-user `try/except`，异常记 `data/logs/` 并继续下一个用户
2. `run_reviewer` / `enforce_all` 移入独立 `try/finally`，保证不被 watcher 异常拖累
3. `add_job(..., misfire_grace_time=3600, coalesce=True, max_instances=1)`
4. 启动时补跑：记录上次 eod 成功日期（落 `data/` 状态文件），若今天是交易日且尚未跑过，则在启动后补跑一次

**验收**：人为让第一个用户抛异常 → 第二个用户仍被处理且复盘执行；把 `misfire_grace_time` 生效后模拟"20:20 关机、21:00 开机"→ 补跑触发。

**工作量**：中　**风险**：低

### P0-4　配了 Key 反而拿不到工具结果（D4 / D5 / D6）

**证据**：
```341:346:src/agents/planner.py
    llm_calls = llm_plan(...)
    if llm_calls is not None:      # 空列表 [] 也不是 None
        return llm_calls           # → runner 直接 break，不回退
    return heuristic_plan(...)
```
- `planner.py:324` 只取 `msg["tool_calls"]`，**模型已写好的 `msg["content"]` 被丢弃**
- `llm.py:68` `tool_choice` 恒 `"auto"`，从无 `"required"`
- `planner.py:333-336` 参数 JSON 解析失败 → 盲调 `{"question": 原文}`

**现象**：模型在 `auto` 下直接用自然语言回答 → 一个工具都不调 → 用户看到"没有调用到可用 Tool"，而实际上有 28 个工具可用、也有 Key。

**修复**：
1. `plan()` 改为 `if llm_calls:` 才用，否则 `return heuristic_plan(...)`
2. `llm_plan` 捕获 `msg["content"]` → 作为 `direct_answer` 返回，交给 `write_answer` 使用（不再丢）
3. 第 1 轮 `auto`；若返回空 `tool_calls` 且尚无 observations → 用 `tool_choice="required"` 重试一次；仍失败才回退启发式
4. 参数解析失败：写 `ctx.llm_notice`（复用 `planner.py:272-281` 的 `_note_llm_error`）并**跳过该调用**，不要盲调

**验收**：
- 用例：mock LLM 返回 `tool_calls=[]` + `content="平安银行现价 11.2"` → 最终答案应含模型原文或走启发式取数，**不能**出现"没有调用到可用 Tool"
- 用例：mock 非法 JSON arguments → 不产生盲调，且 `llm_notice` 有记录

**工作量**：中　**风险**：中（改的是主链路，需保证无 Key 时行为不变）

---

## 2. P1：会踩坑 / 静默丢数据

### P1-1　"开开关就能用"是陷阱（D2 / D3 / D1 / D11）

**证据**：
```45:47:src/tools/loader.py
        if spec.id in {s.id for s in registry.all()}:
            continue                                  # 已注册 → yaml 完全不生效
        registry.register(spec, _disabled_run(spec))  # 未注册 → 永远挂空壳
```
`_disabled_run`（`:14-23`）恒返回 `ok=False`。

**后果链**：把 `web_finance_search.yaml` 改成 `enabled: true` → 大模型**看得到**该工具（因为 `schemas_for_llm` 只看 `enabled` 标志）→ 调用 → 必失败 → 答案里出现"等待资讯 Tool"。
**而 `R-20260923` 分期方案的落地路径正是"开这个 yaml"** —— 文档正在把人带进坑。

**修复**：
1. `load_manifests` 改为：id 已存在 → **只更新** `description / enabled / reason`，不换 fn；id 不存在 → 从代码注册表查 fn，查不到才用 `_disabled_run`
2. 启动断言：`enabled=True` 且 fn 是 `_disabled_run` → 记 warning（含 id），便于一眼发现"声明了但没实现"
3. 统一 id：`futures_quote` → `futures_map`（或让代码注册 `futures_quote`），二选一
4. 删除 `fund_holding.yaml` / `export_share.yaml`（已是死配置，且描述与 `enabled` 自相矛盾），改为在代码注册处写 description

**验收**：把任一 yaml 的 `enabled` 改 true/false 后调 `/api/agent/tools/reload`，`schemas_for_llm` 立即变化（无需重启）；把 `web_finance_search` 置 true 时启动日志出现 warning。

**工作量**：中　**风险**：低

### P1-2　静默失败三连（A8 / A5 / A6）

| 项 | 现象 | 修复 |
|---|---|---|
| A8 | `watcher.py:307-310` 自定义规则 spec 校验失败 `continue`，界面显示"已启用"却永不执行 | 记 warning；在预览结果里返回 `skipped` 及原因；前端规则列表对无效规则标灰 |
| A5 | `_alert` 有 `as_of`（`:189`）但 `Alert` 模型无该列，档位只拼进 detail 文本 | `models.py` 加 `as_of` 列 + `migrate.py` 补列 + `Alert(**kwargs)` 写入 + `_alert_payload` 输出 |
| A6 | `_rule_web_sources` 全程无 `_write_snap` → 同一篇文章隔天重复提醒 | 按 `(job_key, code6, url集合)` 写快照指纹，下次比对；与既有 `_write_snap` 同机制 |

**验收**：无效规则在预览里可见；提醒列表能按档位筛选；同一 URL 隔天不再重复进今日。

**工作量**：小～中

### P1-3　非交易日白打接口（A7）

**证据**：`watcher.py:350-352` 先按 `active_keys` 拉池，**之后**才在 `:359-360` 判断"session 任务在非交易日跳过"。

**修复**：把"是否需要 session 池"的判断提到拉池之前：只有 `trading_today` 为真、或存在 eod 类型需要池的 job 时才拉。

**工作量**：小

### P1-4　复盘链路（A10 / A11）

- `reviewer.py:283` 发布 `watch.reviewed`，但 `channels.py:50-52` 只订阅 `watch.hit` / `watch.digest` / `universe.changed` → **死路**
- `reviewer.py:234-239` 只捞 `pending/deferred`，`info` 类一律标 `skipped` 后不再复查

**修复**：
1. 二选一：给 `watch.reviewed` 接订阅者（写 `alerts.log` / 发 webhook），或删掉这行发布（不留死代码）
2. 复盘页提示"20:20 未开机则当日不补"，并在补跑实现后（P0-3）自动消除
3. 允许对 `skipped` 的提醒手动重算（前端「复盘」页加一个重算入口）

**工作量**：小

### P1-5　流式会话可靠性（D8 / D9）

**证据**：`routes.py:1289` `done = persist(final)` 在 `for ev in stream:` 之后；流中任一异常 → 生成器关闭 → **整轮对话丢失**。
`routes.py:1270` 的 `bus.publish("ask.answer", ...)` 同样无订阅者。

**修复**：
1. 流开始即写 user turn + 占位 assistant turn；结束时更新（或用 `finally` 兜底）
2. 新增 `{"type":"error","message":...}` 事件（不破坏既有 `tool`/`token`/`done` 三事件约定，仅扩展）
3. 整轮加总耗时上限；前端加 `AbortController`
4. `routes.py:1250` 找不到会话应**抛错**而不是静默新建（否则 session_id 变化、历史链断裂）

**验收**：中途断开连接后 `/agent/sessions` 仍能看到该轮；工具抛异常时前端收到 error 事件而非断流。

**工作量**：中

---

## 3. P2：一致性与可维护性

| 项 | 修复 |
|---|---|
| D10 `always_tools` / `forbidden` 不执行 | `runner.iter_agent` 首轮强制注入 `always_tools`；`write_answer` 后加禁用句式过滤。**含"禁荐股"合规红线**，建议与 P1 同批 |
| A3 `start_scheduler` 静默返回 None | 缺 apscheduler 时记 error 日志，并在 `/api/health` 暴露 `scheduler_running` |
| A4 调度器持有旧 `market` | 改为每次 tick 时从 `routes` 重新取（或由 `ensure_market` 回调通知），避免切离线/换证书后仍用旧 client |
| D12 会话标题 | 统一走 40 字截断（`sessions.py:50-53` 的逻辑应用到所有情况） |
| D13 `load_policy` 未知 agent 静默降级 analyst | 抛 `ValueError`，避免 `agent=reviewer` 静默读 analyst 配置 |

---

## 4. 实施分期

| 期 | 内容 | 目标 | 依赖 |
|---|---|---|---|
| **S1 止血** | P0-1 缓存、P0-2 池缓存、P0-3 调度健壮性 | **直接省钱 + 不再静默丢复盘** | 无 |
| **S2 可用** | P0-4 规划器、P1-2 静默失败、P1-3 非交易日 | 配了 Key 真的好用；失败看得见 | S1 |
| **S3 正确** | P1-1 loader、P1-4 复盘、P1-5 流式、P2 全部 | 消除"声明与执行不一致" | S2 |
| **S4 接线** | U4（Agent 共用监控白名单） | 唯一一条"源已在手只差接线"的欠账 | S3 后（依赖 loader 修好才能开 yaml） |

**S4 说明**：`scan_sources()` / `sources_for()` 已能跑（监控侧在用），只需在 `research_tools.py` 新增一个走 `sources_for()` 的工具，替换 `policy_news` / `web_finance_search` 的空壳。**必须先完成 P1-1**，否则改 yaml 不生效。

## 5. 与既有欠账的关系

- **新增**（本文首次记录）：A1–A8、A10–A14、D1–D13 —— 均属"已实现但有缺陷"，不在 U1–U20 内
- **已有且仍成立**：U1（期货占位，`watcher.py` 无分支已复核）、U2/U3（资讯/政策工具未接源）、U4（Agent 不共用白名单）、U9（`invalid_if` 只存不执行）、U10、U20
- **U4 在本文被拆成两半**："白名单不共用"（欠账，S4）与"news/policy 跨日重复提醒"（缺陷 A6，S2）——后者是前者的前提

## 6. 门禁

按 `R-20260921` 的约定：**未勾选开工前不改代码**。本文每条修复都需要单独勾选后才实施。
