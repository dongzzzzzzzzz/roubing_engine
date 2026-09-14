# roubing_engine 修复实施报告 V1

日期：2026-09-10

项目：

- `/Users/lee.dong/Documents/ChatGPT/test-stock-1/roubing_engine`

对照文件：

- `/Users/lee.dong/Documents/ChatGPT/test-stock-1/roubing_research_2026/roubing_ai_driven_stock_selection_engineering_v1.md`
- `/Users/lee.dong/Documents/ChatGPT/test-stock-1/roubing_research_2026/roubing_engine_implementation_review_v1.md`
- `/Users/lee.dong/Documents/ChatGPT/test-stock-1/roubing_research_2026/roubing_2026_fulltext_logic_analysis_v4_architecture.md`

## 一、实施结论

本轮没有把系统改成新的通用量化框架，而是围绕原方案最关键的五条主线修复：

1. 时间快照；
2. 不可变事实；
3. 节点生成的候选全集；
4. 角色、竞争组和逐票任务；
5. 程序级审计与逐日回放。

评审报告中的四个 P0 已完成代码修复。大部分 P1 工程问题已经修复；板块指数历史、官方监管规则正文、长期逐日 universe 和历史 L2 仍保留明确 TODO/BLOCK，不伪装为已经解决。

原有 `runs/20260908` 结果没有删除。它被标记为 `LEGACY_REQUIRES_RERUN`，不能继续作为正式回放计划输入。

## 二、已经完成的关键修复

### 1. Stage D 时间隔离

- 建立 `AUCTION_0925` 和 `OPEN_0935` 两个物理快照；
- 09:25 快照只允许早盘竞价和正式开盘撮合；
- 09:35 快照只增加截至 09:35:59 的分钟和成交事实；
- 删除 T+1 收盘价、全天涨幅、最终涨停和收盘指数；
- 递归扫描禁止出现的未来结果字段；
- 检查每个分时事件不得晚于快照；
- 收盘结果只能写入 `evaluation/`。

### 2. 早盘与尾盘竞价分离

- 每个竞价点增加 `session_type`；
- 09:15—09:25 标记为 `OPENING_AUCTION`；
- 14:57—15:00 标记为 `CLOSING_AUCTION`；
- 旧数据即使没有 `session_type`，验证阶段也会按时间重新过滤；
- 竞价过程末点改名为 `last_observed_process_price`，不再冒充正式开盘价；
- 正式价格仍以 `opening_match` 为准；
- 摘要输出 `first_time`、`last_time` 供审计。

2026-09-09 的 `600108.SH` 重新读取后：

- 竞价过程首点：09:15:01；
- 竞价过程末点：09:24:58；
- 末点价格：5.79；
- 原先误读的 14:59:58 和 5.71 已被排除。

### 3. 事实仓库不再被定向补采破坏

- `write_dataset()` 明确区分 `replace` 和 `merge`；
- `capture_codes.py` 永远使用 merge；
- `run_capture.py --max-codes` 使用 merge；
- 不同数据集按业务主键去重；
- 每次非空抓取先保存到不可变 `_captures` 版本目录；
- 规范层再做 merge/replace；
- manifest 新增抓取范围、写入方式和本次抓取行数。

### 4. 候选池不再等同于涨停榜或 top 25

- 删除“全部二板以上 + 封单靠前首板，最多 25 只”的统一短名单；
- Stage B 读取完整当日涨停、炸板和跌停观察集；
- G2/G4/G5 保持对应节点日首板池；
- G3/G12 必须由节点明确股票代码；
- G6 纳入旧核心、容量、历史方向成员和分歧抗跌观察对象，不要求今日涨停；
- G7 从方向成员和旧角色中枚举容量观察对象，并附成交事实，不设置统一成交额门槛；
- G8 保留同日起算完整队列及失败者；
- G9 同时保留旧核心与新候选；
- G10 合并节点日低位首板与方向旧角色/容量观察对象；
- G11 在方向已知时观察方向内停止跟跌者，方向和主动大单都缺失时直接 `BLOCKED_DATA`，不再退化成高板池或任意 top-N。

逐日 universe 不连续时，相关生成器标记 `PARTIAL_DATA`；该池中的股票不得升级为主候选。

### 5. Schema、忠实度和审计成为硬阻断

- 从顶层必填键升级为递归结构校验；
- 校验节点、候选、路径、竞争组、Stage D 状态枚举；
- 候选必须匹配 Stage B 打开的 generator + anchor_date；
- 候选必须真实存在于相应确定性池；
- `letter_carrier` 当前程序级只允许 `UNKNOWN`；
- 禁止 score、probability、position、allocation 等固定打分、概率和仓位字段；
- `PARTIAL_DATA` 不得产出主候选；
- READY/PARTIAL_DATA 中每个池成员必须被明确选择或排除；
- 审计 PASS 时 violations 必须为空；
- Schema、fidelity 或 audit 任一失败，不写正式账本、作战卡和可执行计划；
- 失败结果只保留为 draft 供修订。

### 6. 路径、竞争组和负样本

- Stage C 强制先推理主路径、替代路径和不行动路径，再建立竞争组，最后讨论股票；
- 路径必须说明钱从哪里来、谁买、谁卖、如何承接、谁接棒和失效事实；
- CompetitionGroup 成为独立结构，包含可比依据、成员、不可比对象、两两关系和次日确认；
- 所有未选池成员必须写入 `excluded_candidates` 及自然语言原因；
- 收盘评价同时保存选中候选和排除候选，防止只保留后来赢家。

### 7. 逐日账本和回放闭环

- 账本保存昨日阶段、今日阶段、迁移证据和反证；
- 保存 previous_role、new_role、进入事实、继续任务、退出条件、竞争组和路径；
- Walk-forward 顺序改为：

```text
捕获 T+1 事实
→ 验证上一交易日 APPROVED 计划的 AUCTION_0925
→ 验证 OPEN_0935
→ T+1 收盘后写 evaluation outcome
→ 生成并审计 T+1 新盘后计划
```

- 收盘 outcome 只计算当时已经可得的一日结果；更长周期结果不能提前写入；
- 验证和评价文件引用追加到原计划账本。

### 8. 原文知识库

- 282 篇 corpus 不再只保留前 400 字；
- 每篇保存完整正文、哈希、日期、标题和 URL；
- Stage B/C/D/audit 分别检索相关原文节选；
- 37 条结构化规则继续作为压缩合同；
- 原帖用来恢复语境，不允许把个案数字升级成通用阈值。

### 9. 固定阈值和错误技术特征

- 删除 `hold_exit.py` 的核心涨幅低于 3%、MA5、平台下 3%、对手多涨 3% 自动退出；
- “该强不强”和角色替代必须对照冻结任务、事件顺序、板块响应和真实竞争者；
- 平台不再用包含当前 K 线的固定 12% 算法；
- 只输出 T 日前 5/10/15 日原始区间事实；
- 哪段区间构成真实压力仍由当前节点和原文语境判断；
- 动作检测只能读取声明快照内的分钟数据。

### 10. 新增市场、公告和监管事实入口

- 全市场涨跌家数；
- 全市场总成交及相对上一交易日变化；
- 昨日涨停股今日买方反馈；
- 公告列表采集和真实发布时间过滤；
- 当前 F10 题材快照标注 `historical_safe=false`，禁止历史回填；
- 监管规则建立版本表和生效日选择器；
- 未录入官方规则正文时返回 `BLOCKED_DATA`，不计算异动距离。

## 三、验证结果

### 静态解析

- 52 个项目及测试 Python 文件全部通过 AST/compileall 解析。

### 自动测试

- 15 项测试全部通过；
- 覆盖竞价时段隔离、09:35 后验字段、分钟截止时间、仓库 merge、不可变 capture、公告发布时间、递归 Schema、A/B/C/D、固定打分/仓位、PARTIAL_DATA、池外候选和审计阻断。

### 确定性样例

- 2026-09-08 全市场日线比较：5547 只股票；
- 上涨 3414、下跌 2028、平盘 105；
- 总成交较前一交易日增加 0.72%；
- 发现 2026-09-07 的 universe 缺失，系统不再错误地把 2026-01-30 当作“昨日买方反馈”；
- 种植业 G6 当前能产生 8 个含非涨停/炸板成员的方向观察对象；
- 因逐日 universe 不连续，该池正确标记为 `PARTIAL_DATA`；
- 全市场 G11 在主动大单和方向都缺失时正确标记为 `BLOCKED_DATA`；
- G10 在官方监管规则未录入时正确标记为 `PARTIAL_DATA`。

## 四、明确没有假装完成的部分

以下仍在项目 TODO 中：

1. 板块指数、板块成交额和非涨停板块扩散尚未完整接入；
2. `theme_registry.json` 尚需逐条加入有证据的同义题材映射；
3. 官方监管规则的正文、发布时间、生效日、失效日和哈希尚未逐条录入；
4. 停复牌、重点监控和风险提示尚未接入；
5. 当前逐日 universe 日期不连续，长期主流、第一次分歧和旧角色迁移仍受限；
6. 历史 L2、完整委托流和早期竞价过程仍然 BLOCK；
7. 尚未用真实模型重新跑完一段连续交易日；目前完成了确定性 dry-run、单元测试和模拟流水线审计阻断测试；
8. 尚未建立 CI。

这些缺口不会由 AI 自行补造：生成器和事实包会标记 `PARTIAL_DATA`、`BLOCKED_DATA` 或 unknowns。

## 五、主要文件

- 项目说明：`roubing_engine/README.md`
- 实施 TODO：`roubing_engine/IMPLEMENTATION_TODO.md`
- 时间快照：`roubing_engine/roubing_engine/warehouse/timebox.py`
- 竞价/09:35 事实：`roubing_engine/roubing_engine/reasoning/validation_factpack.py`
- 仓库写入：`roubing_engine/roubing_engine/collectors/storage.py`
- 候选生成：`roubing_engine/roubing_engine/candidates/generators.py`
- 候选事实池：`roubing_engine/roubing_engine/candidates/pools.py`
- Schema：`roubing_engine/roubing_engine/reasoning/schemas.py`
- 忠实度检查：`roubing_engine/roubing_engine/evaluation/fidelity.py`
- EOD 硬门：`roubing_engine/roubing_engine/reasoning/eod_pipeline.py`
- Stage D：`roubing_engine/roubing_engine/reasoning/validate_pipeline.py`
- 逐日回放：`roubing_engine/roubing_engine/reasoning/walk_forward.py`
- 状态账本：`roubing_engine/roubing_engine/state/ledger.py`
- 原帖索引：`roubing_engine/roubing_engine/rules/corpus_index.py`
- 公告/F10：`roubing_engine/roubing_engine/collectors/f10_context.py`
- 监管版本入口：`roubing_engine/roubing_engine/rules/regulatory.py`
- 测试：`roubing_engine/tests/`

## 六、下一轮建议

下一轮不要继续扩提示词，按下面顺序推进：

1. 补齐连续逐日 universe；
2. 接板块指数与板块成交；
3. 维护有证据的题材映射；
4. 录入正式监管规则和公告状态；
5. 选一段连续交易日进行真实 Stage B→C→audit→09:25→09:35 回放；
6. 根据失败样本修正候选来源和事实缺口，不根据收益反向改规则。
