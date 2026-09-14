# roubing_engine 最终方案对齐与真实回归报告

日期：2026-09-14

## 一、最终结论

当前实现已经从“按板位和候选数量自动选股票”改为：环境和方向关系 → 方法节点 → 节点打开任务 → 任务决定股票功能 → 同任务竞争 → 封闭次日条件树。

2026-03-02 真实盘后回归最终结果：

- `run_status = APPROVED`
- Stage B/C1/C2 Schema 与程序 fidelity：全部通过
- 独立审计：`PASS`
- `primary_path = NONE`
- 动作任务：0
- 动作股票：0
- 最终计划：`NO_ACTION`

这不代表策略已经盈利，只代表本次没有被程序强行制造出主线、任务或股票，工程链路与审计合同通过。

## 二、此前为什么偏离方案

原方案要求：环境 → 主流 → 节点 → 角色功能 → 真实竞争组 → 次日预期 → 盘中验证。

此前实现却存在四类根本偏差：

1. 把最高板、板位和静态强度变成隐含固定优先级。
2. `task_resolver` 能绕过节点，根据候选池形状自动造任务。
3. Stage C 会受候选数量和是否容易收敛影响，并混比不同任务、不同角色股票。
4. Stage D 没有完全封闭计划身份和上下文，存在盘中重新解释或换票风险。

问题不是 V4 的动态分析方向错误，而是此前工程没有守住每一层的权限边界。

## 三、现在每一步怎么做

```text
T 日结构化事实
→ Stage B 逐一比较全部方向
→ 至多一个主路径，也允许 NONE/BLOCKED_DATA
→ 只有 ACTION_READY 方法节点可以打开任务
→ C1 在看不到股票和数量时先选择任务
→ C2 只查看已选任务股票并比较相同功能
→ 计划编译器收敛为 0、1 或 2 个动作叶子
→ 09:25 只验证盘后叶子，最多保留一个对象
→ 09:35 只验证 09:25 留下的对象
→ 程序硬门与独立审计共同决定正式结果
```

### Stage B

看市场宽度、成交、涨跌停和炸板、昨日强势买方反馈、每个方向的梯队、失败反馈、容量承载、扩散、前序账本和数据缺口。

最高板、涨停家数和成交额只能作为关系证据。无法形成多关系支配时必须输出 `NONE`，不能强选商业航天或任何固定题材。

### 节点

节点必须说明原阻力、当日变化、事实引用、roubing 方法、确认和取消条件。只有 `ACTION_READY`、合法 generator、冻结范围和对应规则同时成立才可生成任务。

新增硬门：G8 共同首板或同日起步的起算日当天只能建立唯一性观察组，不得当天 `ACTION_READY` 或打开动作任务。

### C1 任务选择

C1 看不到股票代码、名称、数量和池大小，只能根据主路径、节点前态、缺失功能、进入和退出条件选任务。没有合法任务时必须引用冻结的不行动规则并输出 `NONE`。

### C2 股票比较

C2 只看 C1 已选任务对应的冻结股票池：

- `ACTION_COMPETITOR`：承担同一任务，允许比较；
- `VALIDATION_ONLY`：只验证方向或分支，禁止买入；
- `NOT_RELEVANT`：不属于当前任务。

比较必须来自当前任务允许的功能证据。程序不再用“竞价态度 + 换手”或“封板效率 + 封单”这种单案例公式自动排列主备。

两只无法形成单边功能优势时保持 `SYMMETRIC_UNRESOLVED` 并不行动；三只以上仍未解决时强制 `NO_ACTION`。

### 角色

正式功能角色包含核心、容量、补涨、伴飞、二波伴生、旧核心残余、跟风和 `UNKNOWN`；角色状态包含 `CANDIDATE/PROVISIONAL/CONFIRMED/REPLACED/CANCELLED/UNKNOWN`。

角色必须有进入事件、当前功能、次日任务和退出条件。A/B/C/D 对新股票仍默认 `UNKNOWN`，不得猜测。

### Stage D

09:25 只能在盘后动作叶子中验证，不能新增股票。PRIMARY 只是降级时不能切 BACKUP；只有 PRIMARY 直接失败且 BACKUP 独立完成自身任务时才能切换。

09:35 只能接收 09:25 保留的唯一对象。缺分钟线、逐笔、板块或必要验证事实时必须写 `DATA_INSUFFICIENT`，不能确认承接、主动性、共振或唯一性。

## 四、原审计问题的最终处理

| 问题 | 处理 |
| --- | --- |
| 固定方向优先级 | 删除高度不可逆优先级，改为方向逐对关系支配 |
| resolver 绕过节点 | 任务只允许由 `ACTION_READY` 节点打开 |
| 池里有票就 READY | 同时检查节点、generator、冻结范围和规则合同 |
| 按候选少选任务 | C1 不可见股票与数量，并有非法理由硬门 |
| 被反推与角色替代混淆 | 增加事件顺序、参照物、独立性和替代依据 |
| 非相邻账本当昨天 | 只接受交易日历确认的相邻前一日 |
| 题材混组 | 使用带生效日期的题材映射和边界合同 |
| 历史规则穿越 | 规则、原帖和监管版本按回放日期截止 |
| 事实不可追踪 | 环境、方向、买方反馈和个股均生成 `fact_id` |
| 环境门过松 | 历史迁移与当日横截面比较分开 |
| 通用任务无规则 | 每类任务绑定必需规则和证据家庭 |
| 节点污染无关任务 | 冻结方向、节点、起算日、动作池和验证池 |
| 首板任务重复 | generator 只映射一个正式任务类型 |
| 跨方向备选虚构 | 备选必须有独立路径、节点和任务 |
| Stage C 读取全市场 | 拆为 C1 选任务、C2 只读已选股票 |
| 审计输入不完整 | 审计接收完整事实、B/C1/C2、任务池、候选池和编译计划 |
| 固定十篇原帖 | 审计按实际节点、角色、主动性、退出和替代结构动态召回 |
| 缺角色候选状态 | `role_status` 进入 Schema、fidelity、计划和账本 |
| 单案例泛化主备 | 删除自动排序，必须由当前任务功能事实形成单边结论 |
| 两套候选架构 | 正式唯一入口为 `reasoning/task_resolver.py` |
| 测试固化旧错误 | 改为验证方案纪律与反例硬门 |
| 旧结果冒充新结果 | 新运行先失效旧正式产物，失败不得保留旧 APPROVED |
| 外部股票 skill 污染 | 隔离 Codex home，禁用插件、用户规则和 skills，并扫描污染 |

## 五、2026-03-02 真实回归过程

本次不是一次通过：

1. 第一次：观察节点错误保留 `generator=G8`，被 `BLOCKED_FIDELITY_STAGE_B` 拦截。
2. 第二次：C1/C2 已输出 `NONE/NO_ACTION`，但两个 `NONE` 没有完整引用 `no_action_rule_ids`，被独立审计 `BLOCKED_AUDIT`。
3. 第三次：C1 完整引用冻结不行动规则，最终 `APPROVED`，审计 `PASS`。

最终逐阶段结论：

- 油服工程、石油化工、电网设备、稀有金属、商业航天互有优劣；
- 没有任何方向形成多关系全面支配；
- `primary_path = NONE`，没有按最高板强选商业航天；
- 油服工程九只共同首板只形成 G8 观察组；
- 节点为 `OBSERVATION_ONLY`，`generator=null`；
- 任务 0 个，动作股票 0 只；
- 最终 `NO_ACTION`。

本次正式盘后回归没有读取或恢复 `runs/_deferred_20260303` 中的 2026-03-03 数据。

## 六、为什么会看到 9 月 14 日

`_provenance.generated_at=2026-09-14...` 是模型实际执行时间，不是 3 月 2 日行情日期。正式结果保留它用于审计，但此前它也进入了下游模型任务包，容易造成误解。

现已改为：正式结果继续保留 `_provenance`；C1、C2、EOD audit 和 Stage D audit 的模型输入通过 `provenance.model_view()` 删除运行时元数据；市场边界仍是 `as_of=20260302 CLOSE`，规则和审计原帖仍按 2026-03-02 截止。

历史任务包是实际执行记录，不做事后篡改；新运行会生成不含墙上时钟日期的下游输入。

## 七、用户明确决定不修改的事项

“盘后 `NO_ACTION` 时自动跳过 Stage D”经用户明确决定不修改，相关代码和测试已完整回退。`run_single_day` 与手工 Stage D 入口保持原行为，本项不算待完成缺陷。

## 八、自检

- 最新全量测试：122/122 通过；
- `compileall`、Schema、282 篇语料数量检查：通过；
- 2026-03-02 正式结果用最新代码重新确定性校验：Stage B 零违规、Stage C fidelity `PASS`、计划编译 `PASS`；
- 最终仍为 `NO_ACTION`。

## 九、主要修改位置

- `roubing_engine/reasoning/eod_pipeline.py`
- `roubing_engine/reasoning/task_resolver.py`
- `roubing_engine/reasoning/plan_compiler.py`
- `roubing_engine/reasoning/condition_tree.py`
- `roubing_engine/reasoning/validation_factpack.py`
- `roubing_engine/evaluation/fidelity.py`
- `roubing_engine/reasoning/provenance.py`
- `roubing_engine/reasoning/prompts.py`
- `roubing_engine/reasoning/schemas.py`
- `tests/test_pipeline_gates.py`
- `tests/test_reasoning_chain.py`
- `tests/test_condition_tree.py`
- `tests/test_guardrails.py`

## 十、仍不能宣称完成的内容

以下是此前明确暂缓的历史工程：多日历史状态和角色迁移、缺失历史分钟线与逐笔盘口恢复、多日收盘回评、长期 walk-forward 与收益统计。

因此当前只能确认“工程按方案运行且本次真实审计通过”，不能确认“策略已经被统计证明有效”。
