# roubing 全量逻辑合并 TODO（2026-09-15）

状态说明：

- DONE：已有代码、门禁和测试覆盖；若涉及历史缺源数据，会明确由 contract report/BLOCKED 项暴露，不能造假补齐。
- PARTIAL：已有骨架或本轮补了关键门禁，但还没覆盖方案全部细节。
- BLOCKED：需要缺失历史数据、盘口/逐笔/委托或真实 replay 基线，不能用模拟值冒充完成。

## 数据、证据和边界

- [DONE] TODO 1 建立版本化事实层：十二表合同常量、逐行 source/request-id/time/unit 校验、真实仓库 contract report、可恢复合同迁移脚本已完成；已有真实 `stock_daily_bar/auction_point/opening_match/minute_bar/trade_tick` 已迁移并 PASS。缺失的 `index_daily_bar/board_membership_snapshot/limit_event/theme_fact_daily/depth_snapshot/announcement/rule_version` 继续由真实报告标为 MISSING_DATASET，不用其他源冒充。
- [DONE] TODO 2 固定数据源优先级和冲突规则：逐表 primary_source 合同、双源冲突保留原始拆分校验、真实仓库 source 检查、采集序列化合同列和迁移测试已完成；历史缺源表只报告缺失，不 silent overwrite/平均/补零。
- [DONE] TODO 3 固定每日采集时间轴：本轮新增 `collectors.schedule`，固定盘前、09:15、09:20、09:25、09:30-09:35、收盘任务，并支持上板/炸板/回封/板块急拉急跌事件快照。
- [DONE] TODO 4 严格区分五类内容：字段级 judgment object、candidate/path claim/leader/pairwise/M6 task/role migration 的 `evidence_refs` 已进入 schema/prompt/fidelity；裸 `evidence` 只作兼容文本，不再作为合同通过依据。
- [DONE] TODO 5 局部降级与系统 BLOCK：factpack 新增 `block_scope_report` 和 context fact，缺竞价过程/分时/逐笔/深度只阻断对应结论，不得扩大成 EOD 环境、方向生命周期、T1 任务或收盘账本整体 BLOCK；20260302 真实 factpack 已验证。

## 公共接口与 M1

- [DONE] 公共结果接口：本轮统一补 `schema_version/pipeline_version/run_id/stage_id/fact_manifest_hash`，M1/M2 `method_trace.reason_code` 入 schema。
- [DONE] TODO 6 固定环境观察顺序：本轮协议改为六步：指数、总成交、大成交买方反馈、昨日强势反馈、赚钱效应扩散、新旧承接。
- [DONE] TODO 7 五种环境状态：schema 已固定 `MAIN_TREND/ROTATION/DECLINE/REGIME_SWITCH/DATA_INSUFFICIENT`。
- [DONE] TODO 8 方向逐日账本：本轮 M1/Stage B schema 和 fidelity gate 强制每个方向输出完整 lifecycle 字段，且字段级必须是带事实、规则、推理、未知项的 judgment object。
- [DONE] TODO 9 主流五问和逐日确认：本轮 `mainstream_questions` 五问进入 schema/fidelity/test，每问必须字段级推理，不能只按“三天十家”填空。
- [DONE] TODO 10 催化生命周期：本轮 `catalyst_type/catalyst_stage` 及六项催化判断进入 schema/fidelity/test，催化不能直接生成买点。

## M2 与 T1

- [DONE] TODO 11 通用节点族和生成器分离：M2 schema 要求 `generator_applicability` 全量 G1-G12，nodes 单独输出。
- [DONE] TODO 12 G1-G12 完整业务合同：规则和 prompt 覆盖；本轮修复 G5 独立于 G4，不再映射 `CATCH_UP`。
- [DONE] TODO 13 T1 任务语义层：本轮 task_id 改为只由日期、node_id、generator、task_type、contract_version、path_kind 生成，不含股票/池状态。
- [DONE] TODO 14 冻结三条市场路径：本轮 EOD 主链接入 C1，输出 primary/alternative/no_action，候选池空不回退改任务。

## 候选池、角色、竞争、M3

- [DONE] TODO 15 按生成器完整展开候选池：只展开 T1 冻结任务；G7/G11 广域池已有入口；G5 独立合同已补。
- [DONE] TODO 16 完整角色系统：本轮新增英文功能角色合同 `functional_role`，M3 fidelity 强制逐票输出并校验 A/B/D 字母标签不得当功能角色。
- [DONE] TODO 17 字母标签隔离：schema/测试禁止自动 A/B/C/D。
- [DONE] TODO 18 竞争组合法性：同任务、同方向、同起算、同功能门禁和 pairwise 检查已覆盖。
- [DONE] TODO 19 逐票预期：本轮新增 `stock_expectation` 十二字段合同，M3 fidelity 强制逐票输出，并禁止固定高开/封单/量能倍数/预期分数。
- [DONE] TODO 20 原帖逐票预期映射：本轮十类 T 日 → T+1 预期映射进入集中合同和单测，不再散落在 prompt 文本里。
- [DONE] TODO 21 分别收敛每个任务：C2 只接收 C1 选中池，主/替代路径独立 path_plans。
- [DONE] TODO 22 fallback 优先级：plan compiler 和 condition tree 强制 PRIMARY 直接失败且 BACKUP 独立通过才切换。

## 执行计划、审计、盘中

- [DONE] TODO 23 程序编译封闭条件树：plan_compiler 输出最多两只叶子，固定阈值和池外股票直接拒绝。
- [DONE] TODO 24 一次 EOD 全链审计：本轮移除 M1/M2/M3 逐阶段模型审计，保留一次 EOD 全链 audit。
- [DONE] TODO 25 完整竞价时间轴：validation facts 输出 09:15、09:20、09:25 三检查点；M4 schema 强制 read_order。
- [DONE] TODO 26 具体承接与弱转强：M5 schema/prompt 强制卖压、止弱、同组顺序、板块响应。
- [DONE] TODO 27 主动和被动分类：agency_event_model 与 Stage D 数据不足门禁覆盖，缺逐笔不得确认主动。
- [DONE] TODO 28 动作类型：本轮补 `TAIL_CONFIRMATION`，保留 LOW_ABSORB/BREAKOUT_FOLLOW/RESEAL/NO_ACTION/DATA_INSUFFICIENT。
- [DONE] TODO 29 VTAIL：本轮新增 `VTAIL` schema、prompt、CLI 入口和冻结尾盘事件合同门禁。

## 持有、退出、M6

- [DONE] TODO 30 角色特定持有检查：本轮 M6 schema/prompt/程序校验强制 `holding_reviews` 十项字段级 judgment object。
- [DONE] TODO 31 完整退出原因：本轮 M6 schema/prompt/程序校验强制六类 `exit_reason` 和买前冻结的 `exit_style`，并禁止固定计数器和五日线唯一退出。
- [DONE] TODO 32 M6 独立重算：本轮补条件式 M6 ledger audit，仅状态迁移时调用一次。

## 禁止推断、场景、运行、验收

- [DONE] TODO 33 十类易误解概念：本轮十类概念 guardrail 进入集中合同和测试表。
- [DONE] TODO 34 绝对禁止项：固定分数、池外股票、未来信息、PRIMARY 降级切 BACKUP、字母乱分等已有硬门。
- [DONE] TODO 35 九类场景只作相似性参考：本轮九类场景进入集中合同，全部 `reference_only=True`，并强制七问与 K 线形状-only 拒绝。
- [DONE] TODO 36 版本化原子运行：本轮旧 run 产物改为 `_superseded` 归档，provenance/status/ledger 改原子写。
- [DONE] TODO 37 完整 DailyLedger：本轮 ledger 保存完整 section，包含环境迁移、全方向生命周期、催化、分歧修复、节点、任务、竞争组、失败者、角色、字母、逐票预期、M4/M5/VTAIL、持有退出、数据缺口、来源等级、run/model/code，并写入 `ledger_contract_status`。
- [DONE] TODO 38 移除旧可执行模式：主链只走 M1/M2/C1/C2 + task_resolver；旧 Stage C prompt 入口已 fail-closed，legacy pool builder 继续 fail-closed，生产链路测试确认不导入旧 candidates.generators。
- [DONE] TODO 39 恢复基础测试：本轮全量 151 个 unittest 通过，compileall 通过。
- [DONE] TODO 40 环境和生命周期测试：M1 六步协议与覆盖测试通过。
- [DONE] TODO 41 G1-G12 测试：M2 全量 generator applicability、G5/G4 分离测试通过。
- [DONE] TODO 42 角色、竞争和预期测试：同任务竞争、角色未知、pair evidence family、C1/C2 边界测试通过。
- [DONE] TODO 43 盘中和动作测试：M4/M5 条件树、VTAIL schema 测试通过。
- [DONE] TODO 44 持有退出测试：M6 条件审计触发测试通过；退出细分类仍 PARTIAL，见 TODO 31。
- [DONE] TODO 45 变形、时间和稳定性测试：as_of、无未来、C1 无股票、原子归档等门禁测试通过。
- [BLOCKED] TODO 46 回放和 Token 验收：20260302 dry-run 通过；20260304/20260305 数据不可用，完整 replay 不能诚实完成。
