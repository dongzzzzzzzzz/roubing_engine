# roubing 全量逻辑实现交接记录（2026-09-15）

本文件给晚上继续接手的 AI 看。不要从当前代码反推 roubing 逻辑；方案优先级仍以 `ROUBING_FULL_LOGIC_TODO_20260915.md` 和用户给的合并实施方案为准。

## 当前结论

- TODO 1-45 已落到代码、schema/prompt/fidelity/ledger/测试或真实数据验证。
- TODO 46 仍然 BLOCKED：只有 20260302 能 dry-run；缺 20260304/20260305 真实 replay/token 验收数据，不能用模拟数据冒充完成。
- 全量测试已过：`./.venv/bin/python -m unittest discover -s tests -p 'test_*.py'`，151 tests OK。
- 编译检查已过：`./.venv/bin/python -m compileall -q roubing_engine tests`。
- 真实 20260302 EOD dry-run 已过：47 themes / 120 observations，临时 run 目录执行，未污染 `runs/20260302`。

## 本轮重点完成的 TODO

### TODO 1：版本化事实层

已完成：

- 新增集中合同：`roubing_engine/reasoning/contracts.py`。
- 固定 12 张事实表合同、主源、必填字段、证据类型、规则来源、生命周期、催化、角色、预期、持仓、退出、场景、DailyLedger section。
- 新增真实仓库合同报告：`roubing_engine/warehouse/contract_report.py`。
- 新增可恢复迁移脚本：`roubing_engine/warehouse/migrate_contract.py`。
- 已对真实仓库已有表做合同迁移：
  - `stock_daily_bar`
  - `auction_point`
  - `opening_match`
  - `minute_bar`
  - `trade_tick`
- 已备份旧 parquet 到：`data/warehouse/_migration_backup/contract_v1/...`。

当前真实仓库报告：

- PASS 表：5 张。
- MISSING_DATASET 表：`index_daily_bar`、`board_membership_snapshot`、`limit_event`、`theme_fact_daily`、`depth_snapshot`、`announcement`、`rule_version`。
- 总状态仍是 `NEEDS_MIGRATION`，这是正确的：这些表缺真实源数据，不能拿别的数据冒充。

### TODO 2：固定数据源优先级和冲突规则

已完成：

- 每张事实表有固定 `primary_source`。
- 冲突规则禁止平均、覆盖、last-write-wins、补零。
- 双源冲突必须保留原始拆分字段。
- `daily_loader` 未来写入合同列：raw/adj price、amount、volume_unit、source、interface、request_id、event_time、change_pct。
- eltdx 序列化器写入合同列：`eltdx_code/source/interface/request_id/event_time/available_at/volume_unit` 等。
- 本地无 `eltdx` 包时，`eltdx_client` 仍可 import；只有真正 live collection 时才报清晰错误。

### TODO 3：固定每日采集时间轴

已完成：

- 新增 `roubing_engine/collectors/schedule.py`。
- 固定盘前、09:15、09:20、09:25、09:30-09:35、收盘任务。
- 支持事件快照：上板、炸板、回封、板块急拉、板块急跌。

### TODO 4：严格区分五类内容

已完成：

- AI 判断字段不是“填空模板”，而是 reasoned object：
  - `status`
  - `evidence_kind`
  - `value`
  - `observed`
  - `inference`
  - `supporting_fact_ids`
  - `counter_fact_ids`
  - `rule_ids`
  - `unknowns`
- M3 candidate、path claim、leader_state、pairwise、M6 task/role migration 增加 `evidence_refs`。
- 裸 `evidence` 只保留兼容文本，不再作为合同通过依据。
- `POST_ASOF_OUTCOME` 不能支撑当前计划。

### TODO 5：局部降级与系统 BLOCK

已完成：

- `evidence_compiler.compile_day()` 新增 `block_scope_report`。
- `day_factpack` 把 `BLOCK_SCOPE_REPORT` 写入 `context_facts` 和 `fact_catalog`。
- 缺竞价过程、分时、逐笔、深度时，只阻断对应结论：
  - 竞价全过程排位迁移
  - 秒级主动大单顺序
  - 逐笔主动/被动归因
  - 完整委托队列变化
  - 撤单主体/队列意图确认
- 不允许扩大成环境、方向生命周期、T1 任务、收盘账本整体 BLOCK。
- 20260302 真实 factpack 已验证：EOD 可用，`block_scope_report.status=PASS`，`eod_reasoning_blocked=False`。

### TODO 8/9/10：方向生命周期、主流五问、催化生命周期

已完成：

- 每个方向强制输出完整生命周期字段。
- 主流五问强制进入 schema/fidelity/test。
- 催化类型和阶段进入合同，不允许催化直接生成买点。

### TODO 16/19/20：角色与逐票预期

已完成：

- 新增英文功能角色合同 `functional_role`。
- 字母 A/B/D 只能作为作者标签，不能当功能角色。
- 新增 `stock_expectation` 十二字段合同。
- 逐票预期生成顺序固定：
  1. T 日角色
  2. T 日表现
  3. T 日板块状态
  4. 同组第二名
  5. 当前监管/剩余空间
- 禁止固定高开比例、固定封单额、通用量能倍数、预期分数。

### TODO 30/31/37：持有、退出、DailyLedger

已完成：

- M6 强制 `holding_reviews` 十项字段级 reasoned object。
- M6 强制六类 `exit_reason` 和两类 `exit_style`。
- 禁止固定计数器和五日线唯一退出。
- DailyLedger 保存完整 section，并写入 `ledger_contract_status`。

### TODO 38：移除旧可执行模式

已完成：

- 生产主链只走 M1/M2/C1/C2 + `task_resolver`。
- 旧 Stage C prompt 入口 `_legacy_stage_c_instructions()` 已 fail-closed。
- `candidates.generators.build_pools_from_nodes()` 继续 fail-closed，防止绕过 task_resolver。
- 测试确认 `eod_pipeline` 不导入旧 `candidates.generators`。

## 本轮新增/重点修改文件

- `ROUBING_FULL_LOGIC_TODO_20260915.md`
- `ROUBING_FULL_LOGIC_HANDOFF_20260915.md`
- `roubing_engine/reasoning/contracts.py`
- `roubing_engine/warehouse/contract_report.py`
- `roubing_engine/warehouse/migrate_contract.py`
- `roubing_engine/collectors/schedule.py`
- `roubing_engine/collectors/eltdx_client.py`
- `roubing_engine/collectors/serialize.py`
- `roubing_engine/reasoning/evidence_compiler.py`
- `roubing_engine/reasoning/day_factpack.py`
- `roubing_engine/reasoning/schemas.py`
- `roubing_engine/reasoning/prompts.py`
- `roubing_engine/evaluation/fidelity.py`
- `roubing_engine/reasoning/close_review_pipeline.py`
- `roubing_engine/features/stock_features.py`
- `tests/test_full_logic_contracts.py`
- `tests/test_guardrails.py`
- `tests/test_pipeline_gates.py`

另有前序已经存在的多处改动：`eod_pipeline.py`、`plan_compiler.py`、`protocols.py`、`provenance.py`、`runner.py`、`task_resolver.py`、`validate_pipeline.py`、`ledger.py`、`daily_loader.py` 等。

## 已执行验证

```bash
./.venv/bin/python -m compileall -q roubing_engine tests
./.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
```

结果：

```text
Ran 151 tests in 86.756s
OK
```

真实数据 dry-run：

```bash
./.venv/bin/python - <<'PY'
from pathlib import Path
from unittest.mock import patch
import tempfile
from roubing_engine.reasoning import eod_pipeline
with tempfile.TemporaryDirectory() as tmp:
    with patch.object(eod_pipeline, 'RUNS', Path(tmp)):
        out = eod_pipeline.run_pipeline('20260302', dry_run=True, with_daily=False)
        print(out)
PY
```

结果要点：

```text
ok True
themes 47
observations 120
```

真实仓库合同报告：

```text
overall NEEDS_MIGRATION
pass_tables 5
missing_tables ['index_daily_bar', 'board_membership_snapshot', 'limit_event', 'theme_fact_daily', 'depth_snapshot', 'announcement', 'rule_version']
```

## 下一位 AI 注意事项

1. 不要把 `NEEDS_MIGRATION` 理解成已失败。已有真实表已经 PASS；整体 NEEDS 是因为 7 张事实表缺真实源数据。
2. 不要用 eltdx `universe` 冒充 Financial-API 的 `limit_event/theme_fact_daily/board_membership_snapshot`。
3. 不要把 JSON schema 当填空表。字段是让模型“推理后结构化落盘”，代码只检查它有没有按事实、规则、未知项表达。
4. 不要动 `runs/20260302` 做验证产物；真实 dry-run 用临时 `RUNS` patch。
5. TODO 46 只有拿到 20260304/20260305 或等价真实 replay/token 基线后才能继续。
