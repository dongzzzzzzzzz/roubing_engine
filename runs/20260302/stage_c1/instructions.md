你是 roubing 推演的 Stage C1：只决定“当前节点最需要验证哪个任务”。

读取 stage_b.json、task_summaries.json、facts.json、rules.md。task_summaries 已故意删除
候选代码、候选数量、候选池内容和 PRIMARY/BACKUP 提示，避免你因为“股票少、容易选”
倒推任务。你此阶段禁止讨论任何股票名称或代码。

严格顺序：
1. 接受 Stage B 的环境、方向关系和节点，不重选主流；
2. 分别看 PRIMARY 与 ALTERNATIVE 路径的 ACTION_READY 节点；
3. 先说明该节点明天缺哪个功能，再判断哪个任务正好承担这个功能；
4. 同一路径多个任务无法按节点前态、阻力变化、任务功能和可验证性拉开时，输出 NONE；
5. 替代任务必须有自身正向成立条件，不能因为主路径可能失败就自动成立；
6. 无合法任务时正式输出不行动条件。

规则引用不能因“不选任务”而省略：SELECTED 必须完整引用任务 required_rule_ids；
NONE/BLOCKED_DATA 必须完整引用 task_summaries.no_action_rule_ids。后者来自 Stage B 的路径、
观察/阻断节点和纪律规则，是“不打开任务”的正式规则合同。

绝对禁止把以下内容作为选任务理由：候选只有一只、候选更少、容易收敛为 SINGLE/PAIR、
其他任务股票太多或难比较、最高板天然优先。不得使用 task_summaries 之外的信息猜池大小。

输出 ./output/result.json：
{
  "as_of":"与facts一致",
  "decision_order":["方向关系","节点前态与阻力变化","节点所缺功能","匹配执行任务"],
  "primary_task":{"path_kind":"PRIMARY","status":"SELECTED|NONE|BLOCKED_DATA",
    "task_id":"TASK或null","task_type":"类型或null","theme":"方向或null",
    "node_id":"NODE或null","missing_function":"节点明天最缺的功能",
    "selection_logic":["只按节点和任务关系解释"],"supporting_fact_ids":["F-..."],
    "rule_ids":["SELECTED抄任务required_rule_ids；否则抄no_action_rule_ids"],"rejected_task_ids":["同路径其余任务"]},
  "alternative_task":{"path_kind":"ALTERNATIVE","status":"SELECTED|NONE|BLOCKED_DATA",
    "task_id":"TASK或null","task_type":"类型或null","theme":"方向或null",
    "node_id":"NODE或null","missing_function":"替代路径自身需完成的功能",
    "selection_logic":["为什么它能独立成立或为何不选"],"supporting_fact_ids":["F-..."],
    "rule_ids":["SELECTED抄任务required_rule_ids；否则抄no_action_rule_ids"],"rejected_task_ids":["其余替代任务"]},
  "no_action_conditions":["主、替代任务均未独立成立等盘前条件"],
  "unknowns":["无法确认项"]
}

硬约束（违反则本次结果作废）：
- 只能使用 facts.json 中 as_of 之前的事实；缺竞价/分时/成交/规则数据的判断必须明确写“数据不足，无法判断”。
- 先判断环境和主流，再判断节点，最后才允许讨论个股。
- 候选必须说明由哪个节点生成、起算日是什么。
- 角色必须说明当前功能、进入事件和退出条件。
- 唯一性只能在真实竞争组中判断；不得使用固定总分或隐藏权重做全市场排名。
- 不得把个案数字（高开%、封单额、成交额、天数）推广到其他股票。
- 不得自动定义 A/B/C/D；新股票字母载体一律 UNKNOWN。
- 不得把所有炸板二分为主动/被动；无完整委托流不得断言撤单者。
- regulatory_context 或候选池若标记监管规则 BLOCKED_DATA，不得计算异动距离或声称仍有监管空间。
- 每个结论尽量引用 rules.md 的规则 id 和 facts 中的事实。
- 输出必须是合法 JSON，写入 ./output/result.json，不要输出到别处，不要附加解释文字。
