# roubing_engine 修复 TODO

更新时间：2026-09-10

状态含义：`DONE` 已实现并有验证；`IN_PROGRESS` 正在实现；`BLOCKED_DATA` 缺当前可得数据；`TODO` 尚未实现。

## P0：会直接制造错误结论

- [x] `DONE` Stage D 分成 `AUCTION_0925` 与 `OPEN_0935` 两个物理快照。
- [x] `DONE` 移除 Stage D 的 T+1 收盘价、全天涨幅、最终涨停和收盘指数。
- [x] `DONE` 增加递归后验字段检查与快照事件时间检查。
- [x] `DONE` 将 09:15—09:25 早盘竞价和 14:57—15:00 尾盘竞价分类。
- [x] `DONE` 竞价摘要只读取早盘区间，并输出首末时间供审计。
- [x] `DONE` 09:25 正式开盘价格继续以 `opening_match` 为准，竞价过程末点不再命名为 final price。
- [x] `DONE` 定向补采改为业务主键 merge，不再覆盖其他股票。
- [x] `DONE` 每次抓取保存不可变 `_captures` 原始版本，规范层再 merge/replace。
- [x] `DONE` 删除 Stage B 统一 top-25 结构性粗筛。
- [x] `DONE` G6/G7/G9 不再限定为当日涨停股；加入历史方向成员和旧角色。
- [x] `DONE` G8 保留同日起算完整队列和失败者，不以后来赢家反筛。
- [x] `DONE` G3/G12 必须由 Stage B 提供明确股票代码，否则 `BLOCKED_DATA`。
- [x] `DONE` G11 在方向已知时枚举方向内停止跟跌事实，或读取节点明确候选；全市场方向未知时返回 `BLOCKED_DATA`，不再等同于高板池或任意 top-N。

## P1：roubing 方法忠实度

- [x] `DONE` 递归 Schema 检查候选、路径、节点、竞争组和 Stage D 输出。
- [x] `DONE` 候选必须同时匹配 Stage B generator/anchor 和确定性候选池。
- [x] `DONE` `letter_carrier` 当前程序级只允许 `UNKNOWN`。
- [x] `DONE` 建立 CompetitionGroup 领域实体并校验组员和对手。
- [x] `DONE` 强制保存 READY/PARTIAL_DATA 池中每个成员的选择或排除决定，收盘评价同时覆盖同期负样本。
- [x] `DONE` Schema、确定性 fidelity 或独立 audit 任一失败，均不保存正式账本/作战卡。
- [x] `DONE` Stage B/C/D/audit 写入输入哈希、规则版本、提示词哈希、模型后端和代码版本。
- [x] `DONE` 扩充逐日账本：方向迁移、角色迁移、节点、竞争组、任务、取消条件、路径和 provenance。
- [x] `DONE` 移除 `hold_exit.py` 的固定 3%、MA5、平台下 3% 和对手强 3% 自动退出。
- [x] `DONE` 日线平台改为 T 日前 5/10/15 日原始区间，不再使用含当前 K 线的固定 12% 平台算法。
- [x] `DONE` 动作检测限定在声明快照内，不再用全天分钟数据冒充 09:35。
- [x] `DONE` 282 篇原帖保存全文，并按 Stage B/C/D/audit 任务检索原文节选。
- [x] `DONE` 补全全市场涨跌宽度、总成交变化和昨日强势买方反馈事实。
- [ ] `TODO` 接入板块指数、板块成交额和非涨停板块扩散数据。
- [ ] `TODO` 根据证据逐条维护 `theme_registry.json`；禁止纯文本相似度自动合并题材。
- [ ] `BLOCKED_DATA` G11 的“持续主动大单”需要历史逐笔/L2；缺失时只能判断日线停止跟跌。
- [x] `DONE` 建立监管规则版本表、官方来源和按生效日选择器；空规则时程序返回 `BLOCKED_DATA`，不编造阈值。
- [ ] `TODO` 逐条下载、校验并录入当时有效的上交所/深交所/北交所/证监会正式规则正文与哈希。
- [x] `DONE` 接入 eltdx 公告和当前 F10 题材采集器；公告按真实发布时间过滤，当前题材快照禁止历史回填。
- [ ] `TODO` 接入停复牌、重点监控和风险提示事实。

## P2：逐日闭环和工程质量

- [x] `DONE` 完整 walk-forward 顺序：T 计划冻结 → T+1 09:25 → 09:35 → 收盘评价 → 新 T+1 计划。
- [x] `DONE` 收盘 outcome 单独写入 `evaluation/`，不进入 Stage B/C/D。
- [x] `DONE` 逐日账本追加验证与评价文件引用。
- [x] `DONE` 修复 Financial-API 毫秒时间使用本机时区的问题，固定为 `Asia/Shanghai`。
- [x] `DONE` 数据完整度从“分区是否非空”升级到行数、股票数、时段和竞价会话覆盖。
- [x] `DONE` 增加 README、标准 `pyproject.toml` 和基础测试。
- [ ] `TODO` 增加真实模型连续回放测试，覆盖 Stage B→C→audit→D 全链路。
- [ ] `TODO` 增加 CI；当前目录尚未纳入独立 Git 仓库，先不伪造 CI 成功状态。
- [ ] `BLOCKED_DATA` 早期历史竞价过程和逐笔盘口无法从当前接口完整恢复，严格盘口回放继续标记 BLOCK。
- [ ] `TODO` 扩大历史逐日 universe 覆盖；当前有限日期不足以完整恢复长期主流和旧角色。

## 验收命令

```bash
PYTHONPATH=. python -m unittest discover -s tests -v
python -m compileall -q roubing_engine run_capture.py capture_codes.py capture_context.py
PYTHONPATH=. python -m roubing_engine.reasoning.eod_pipeline --date 20260908 --dry-run --no-daily
```
