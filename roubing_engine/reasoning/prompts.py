"""Instruction (prompt) builders for each EOD reasoning stage.

Every instruction embeds the plan §28 hard contract and demands the sub-agent
write ONLY output/result.json. Stages read prior outputs to enforce the fixed
decision order (environment/mainstream/node BEFORE stocks).
"""
from __future__ import annotations

HARD_CONTRACT = """
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
""".strip()


def stage_b_instructions() -> str:
    return f"""你是 roubing 交易逻辑的“市场与节点推理”模块（Stage B）。

请阅读当前目录下：
- facts.json：当日确定性事实（题材归组、梯队、全市场宽度与成交、昨日买方反馈、完整涨停/炸板/跌停观察集、竞价强度、日线特征）。
- rules.md：检索到的 roubing 规则片段（环境/节点/纪律）。
- original_posts.md：与当前任务相关的原帖原文节选，用于核对语境；低层个案不得覆盖当前事实。
- yesterday_state.json：昨日状态账本（可能为空，表示无前一日账本）。

任务：仅判断【市场环境】【主流方向及阶段】【当前节点】，不要选个股买点。

请把结果写入 ./output/result.json，结构（键名固定）：
{{
  "as_of": "facts.json 的 as_of",
  "environment": {{"candidate": "MAIN_TREND|ROTATION|DECLINE|REGIME_SWITCH",
                   "supporting": ["事实"], "counter": ["反证"],
                   "migrated_from": "昨日环境或 null", "tomorrow_checks": ["明日验证"]}},
  "mainstream_directions": [
     {{"theme": "涨停原因/方向", "stage": "启动|延续|分歧|修复|主升|震荡|二波|退潮|热点候选",
       "supporting": ["事实"], "counter": ["反证"], "competitors": ["竞争方向"]}}
  ],
  "nodes": [
     {{"node_type": "如 FIRST_MAJOR_DIVERGENCE/BREAKOUT/CORE_SWITCH...",
       "anchor_date": "YYYY-MM-DD 起算/触发日", "theme": "方向或null",
       "trigger_facts": ["事实"], "generator": "G1..G12 或 null",
       "candidate_ids": ["仅G3/G12等单票节点写明确股票代码，否则空数组"],
       "confirm": ["确认任务"], "cancel": ["取消任务"]}}
  ],
  "data_gaps": ["数据缺口或方法未知"]
}}

{HARD_CONTRACT}
"""


def stage_c_instructions() -> str:
    return f"""你是 roubing 交易逻辑的“候选、角色、竞争与次日任务”模块（Stage C）。

请阅读当前目录下：
- facts.json：当日确定性事实与完整观察集；观察集不是候选池。
- stage_b.json：Stage B 已确定的环境/主流/节点结论（必须以它为前提，不得推翻环境结论去凑个股）。
- candidate_pools.json：由节点+起算日生成的【确定性候选池】。这是候选的第一来源。
- rules.md：检索到的 roubing 规则片段（生成器/角色/退出/语义原语/纪律）。
- original_posts.md：核心、容量、补涨、伴飞、二波、唯一性和切换相关原帖节选。

任务顺序不可颠倒：先比较主路径、真正有竞争力的替代路径和不行动原因；再按路径建立真实竞争组；最后才判断逐票角色和次日任务。只在 Stage B 打开的节点对应候选池里工作。

每条可行动路径必须用自然语言回答：钱从哪里来、谁明天最可能买、谁必须卖、买方凭什么承接、会落到哪一层、买入后谁可能接棒、还有什么可复制空间、什么事实会推翻。不得先选股票再补路径故事。

候选来源纪律：
- 候选必须来自 candidate_pools.json 的确定性池（说明来自哪个 generator 和起算日）；
- 若某节点池为 BLOCKED_DATA/EMPTY_VALID，明确写出缺起算日、方向关系、账本或数据；不得从 facts 观察集临时捏造候选；
- `BLOCKED_DATA` 池不得输出候选；`PARTIAL_DATA` 池只能输出待验证/取消观察，必须把 data_blocks 原样写入 unknowns，不能升级为主候选；
- 不得把不在池里的股票升级为主候选。
- 每只候选必须逐字段抄写 candidate_pools 中对应的 generator 和 anchor_date；不能只在 node 自由文本中暗示来源。

请把结果写入 ./output/result.json，结构（键名固定）：
{{
  "as_of": "同 facts",
  "paths": {{
    "primary": {{"desc": "含钱从哪来/谁买/谁卖/如何承接/谁接棒/剩余空间", "confirm": ["竞价/开盘确认"], "cancel": ["取消条件"]}},
    "alternative": {{"desc": "同样完整的竞争路径", "trigger": ["主路径何条失效才接管"], "cancel": ["替代路径自身取消条件"]}},
    "no_action": {{"trigger": ["无新买家/卖压无承接/空间透支/无合适载体/证据不足中的具体原因"]}}
  }},
  "competition_groups": [
    {{"group_id": "方向-节点-功能-起算日",
      "comparison_basis": ["为何同方向/同起算日/同功能而可比"],
      "members": ["组内候选thscode"],
      "not_comparable_with": ["容易被误比但实际不可比的对象及原因"],
      "leader_state": "UNRESOLVED|当前领先者及条件",
      "pairwise_relations": ["A相对B的事件顺序与当前关系，不用分数"],
      "next_confirmation": ["次日如何确认或推翻"]}}
  ],
  "candidates": [
    {{"thscode": "", "theme": "", "node": "", "generator": "G1..G12", "anchor_date": "YYYY-MM-DD",
      "role": "总核心|容量核心|情绪核心|分支核心|助攻伴飞|补涨|低位伴生|二波载体|旧核心残余|跟风|UNKNOWN",
      "letter_carrier": "UNKNOWN 或作者点名字母",
      "competition_group": "同题材/同起算日/同功能标识",
      "competitors": ["同组对手 thscode"],
      "observed_state": ["T日已发生事实"],
      "tomorrow_must_do": ["次日必须完成(自然语言,基于前态/对手/板块)"],
      "acceptable_variants": ["虽非最强但可保留路径的表现"],
      "failure_signals": ["出现即降级或取消"],
      "cancel_if": ["取消条件"],
      "output_tier": "主候选|待验证候选|替代候选|取消或不行动",
      "evidence": ["规则id 或事实"]}}
  ],
  "excluded_candidates": [
    {{"thscode": "候选池中未进入逐票作战卡的股票", "generator": "G1..G12",
      "anchor_date": "YYYY-MM-DD", "reason": "按角色/关系/数据边界排除的自然语言原因，不允许按固定分数"}}
  ],
  "unknowns": ["原文无统一定义或数据不足"]
}}

候选覆盖纪律：READY/PARTIAL_DATA 候选池的每个 generator+anchor_date+thscode，必须且只能出现在 candidates 或 excluded_candidates 一处。这样回放保留同期失败者和负样本，不能只保存后来赢家。

{HARD_CONTRACT}
"""


def stage_d_instructions() -> str:
    return f"""你是 roubing 的“竞价验证器 + 开盘五分钟验证器”（Stage D）。

请阅读当前目录：
- plan.json：T 日盘后作战卡（Stage C 的候选、角色、次日必须完成、失败信号、三路径）。
- validation_facts.json：冻结到文件中 as_of 的 T+1 竞价事实；若 snapshot=OPEN_0935，另含截至09:35:59的开盘五分钟事实。
- rules.md：竞价/承接/主动被动/退出/纪律规则片段。
- original_posts.md：竞价、开盘五分钟、承接和主动/被动相关原帖节选。

任务：只验证 plan 里的候选，不得临时发明新股票。对每只候选，用 validation_facts 的可观察行为判断它是否完成了盘后写下的“次日必须完成”，输出确认/降级/替代/取消。严禁推断或引用 as_of 之后的指数、价格、涨幅、涨停和收盘结果；市场分时缺失时 market_check 必须写数据不足。

请把结果写入 ./output/result.json：
{{
  "tplus1": "同 validation_facts",
  "snapshot": "AUCTION_0925|OPEN_0935",
  "as_of": "同 validation_facts.as_of",
  "market_check": {{"index_held": null, "note": "有快照内指数/板块分时时可改为true/false；缺失必须为null"}},
  "candidate_results": [
    {{"thscode": "", "plan_tier": "",
      "auction_conclusion": "AUCTION_CONFIRMED|AUCTION_NEEDS_OPEN_VALIDATION|AUCTION_DOWNGRADED|ALTERNATIVE_TAKES_OVER|CANCELLED",
      "open5m_conclusion": "CONFIRMED|CONTINUE_OBSERVE|DOWNGRADED|REPLACED|CANCELLED|DATA_INSUFFICIENT",
      "final_status": "确认|降级|替代接管|取消|数据不足",
      "observed": ["具体可观察行为，如：竞价高开X%但开盘五分钟探低Y%后翻红收回；或竞价即弱、开盘杀跌未收回"],
      "vs_plan": "对照该候选盘后‘次日必须完成’逐条说明达成/未达成",
      "reason": ["规则id 或事实"]}}
  ],
  "path_outcome": {{"primary": "主路径是否被确认/取消", "alternative": "替代路径是否接管/取消", "no_action": "是否应不行动"}},
  "unknowns": ["数据缺口"]
}}

{HARD_CONTRACT}
"""


def audit_instructions() -> str:
    return f"""你是独立审计模块，检查 stage_b.json 与 stage_c.json 是否忠实于 roubing 方法。

阅读当前目录：stage_b.json、stage_c.json、rules.md、original_posts.md。

请写入 ./output/result.json：
{{
  "verdict": "PASS|NEEDS_REVISION",
  "violations": [
    "逐条列出：是否把个案当通则/是否遗漏起算日/是否比较了不可比股票/是否用了未来信息/是否给A|B|C|D乱分级/是否用固定分数替代关系/是否缺取消条件/是否直接给股票名单而无环境和节点"
  ],
  "counter_arguments": [
    "反方：主流可能只是一日游/候选可能只是跟风/所谓弱转强可能是假强/所谓分歧可能是推进失败/所谓新核心可能只是被反推 的具体证据"
  ]
}}

`violations` 只允许放实际违规项；“未发现某问题”不能写入 violations。若 verdict=PASS，violations 必须为空数组。反方可能性统一写入 counter_arguments，不要与违规项混淆。

只输出 JSON 到 ./output/result.json。不要修改其他文件。
"""
