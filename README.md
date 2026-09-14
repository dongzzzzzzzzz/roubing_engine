# roubing_engine

这是一个按 roubing 原始逻辑组织的逐日推演工程，不是全市场固定打分器。

固定决策顺序：

```text
不可变事实
→ Stage B 环境 / 主流 / 节点
→ G1—G12 节点候选全集
→ Stage C 角色 / 真实竞争组 / 次日任务 / 三路径
→ Schema + 确定性忠实度 + 独立反方审计
→ APPROVED 盘后计划
→ T+1 AUCTION_0925
→ T+1 OPEN_0935
→ 收盘结果只进入 evaluation
```

## 不可违反的边界

- T 日推演不能读取 T+1 数据。
- 09:25 验证不能读取开盘后数据。
- 09:35 验证不能读取当天收盘价、全天涨幅或最终涨停状态。
- 收盘结果只进入 `runs/<plan_date>/evaluation/`，不得回流 Stage B/C/D。
- 候选只能来自 Stage B 节点打开的 G1—G12 确定性池。
- 不设置统一总分、成交额门槛、高开阈值或跨角色排名。
- 新股票的 A/B/C/D 载体保持 `UNKNOWN`。
- 没有完整委托流时，不自动判断撤单者、主动炸板或被动炸板。
- 数据或方法不足时返回 `BLOCKED_DATA` / `BLOCKED_METHOD`，不得由 AI 补造。

## 安装与测试

```bash
git clone --branch codex/20260303-reasoning-handoff \
  git@github.com:dongzzzzzzzzz/roubing_engine.git
cd roubing_engine
python -m pip install -e .
PYTHONPATH=. python -m unittest discover -s tests -v
```

当前分支的交接入口、2026-03-03 推演结果、文件阅读顺序和继续运行方式见
[HANDOFF_20260303.md](docs/HANDOFF_20260303.md)。

## 只生成任务包，不调用模型

```bash
PYTHONPATH=. python -m roubing_engine.reasoning.eod_pipeline \
  --date 20260908 --dry-run --no-daily
```

## 单日盘后推演

```bash
PYTHONPATH=. python -m roubing_engine.reasoning.eod_pipeline \
  --date 20260908 --backend cursor
```

候选公告与 F10 当前题材可单独补采：

```bash
PYTHONPATH=. python capture_context.py --date 2026-09-08 \
  --codes 600108.SH,600354.SH --datasets announcement,hot_topic
```

公告按实际发布时间过滤；当前 F10 题材快照带抓取时间，不能回填到更早的历史回放。

只有 Schema、确定性忠实度检查和独立审计全部通过，才会写入：

- `runs/<date>/stage_b_result.json`
- `runs/<date>/stage_c_result.json`
- `runs/ledger/<date>.json`
- 次日作战卡

未通过的结果只保存为 `*.draft.json`，`run_status.json` 会记录阻断原因。

## T+1 分时验证

```bash
PYTHONPATH=. python -m roubing_engine.reasoning.validate_pipeline \
  --plan-date 20260908 --tplus1 2026-09-09 --snapshot AUCTION_0925

PYTHONPATH=. python -m roubing_engine.reasoning.validate_pipeline \
  --plan-date 20260908 --tplus1 2026-09-09 --snapshot OPEN_0935
```

Stage D 只接受 `run_status=APPROVED` 的冻结计划。

## 完整逐日回放

```bash
PYTHONPATH=. python -m roubing_engine.reasoning.walk_forward \
  --start 2026-01-05 --end 2026-01-09 --backend cursor
```

逐日驱动会依次完成当日采集、上一日计划的两个快照验证、T+1 收盘评价和当日新计划。历史盘口数据缺失时会明确阻断或降级，不补造。

## 数据仓库

- 规范分区：`data/warehouse/<dataset>/date=YYYYMMDD/part.parquet`
- 原始版本：`data/warehouse/_captures/<dataset>/date=YYYYMMDD/capture=*.parquet`
- 抓取清单：`data/warehouse/capture_manifest.parquet`

定向补采使用业务主键合并，不会删除同日其他股票。每次非空抓取都会先写入不可变原始版本。

## 主题归组纪律

`roubing_engine/rules/theme_registry.json` 是版本化的证据映射表。默认使用恒等映射：没有证据时，即使两个涨停原因文字相似也不会自动合并。映射必须附来源和依据。

## 原帖知识库

仓库内置 282 篇原帖语料及其编译结果。正式推演和审计严格分层：

- Stage B、C1、C2 只读取已经编译的规则和当天冻结事实，不读取原帖；
- 独立审计根据本次实际用到的方法动态检索原帖，只用于寻找误用、反例和个案泛化；
- 原帖中的历史题材、股票和数字不得回填为当天市场事实或通用阈值。

原始语料位于 `reference/corpus/`。如需使用外部语料目录，可设置
`ROUBING_CORPUS_DIR=/absolute/path/to/corpus`。

核心设计方案及历次架构说明位于 `docs/design/`。

当前剩余工作见 [IMPLEMENTATION_TODO.md](IMPLEMENTATION_TODO.md)。
