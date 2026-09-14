const fs = require('fs');
const path = require('path');

const facts = JSON.parse(fs.readFileSync('facts.json', 'utf8'));
const directions = facts.direction_state_facts;
const prevRows = facts.previous_buyer_feedback?.rows || [];
const ENV_BREADTH = 'F-20260302-ENV-A856B87611';
const ENV_LADDER = 'F-20260302-ENV-F6F7FA26F6';
const ENV_PREV = 'F-20260302-ENV-6070A933AC';
const ENV_CONTEXT = 'F-20260302-ENV-F163EC8BEE';
const PRIMARY = '商业航天';
const competitors = new Set(['石油化工', '油服工程', '电网设备', '稀有金属']);
const oilCluster = new Set(['油服工程', '石油化工', '天然气', '油气开采', '燃气', '油气', '油气装备', '油气设备', '油田技术服务', '煤制烯烃', '甲醇', '绿氢绿醇', '绿色甲醇']);

function ladderText(d) {
  const entries = Object.entries(d.ladder_distribution || {}).sort((a, b) => Number(b[0]) - Number(a[0]));
  return entries.length ? entries.map(([k, v]) => `${k}板${v}家`).join('、') : '无封板梯队';
}

function moneyText(v) {
  return `${(Number(v || 0) / 1e8).toFixed(2)}亿元`;
}

function sameNameBuyerText(theme) {
  const rows = prevRows.filter(r => r.previous_reason === theme);
  if (!rows.length) return null;
  const up = rows.filter(r => r.today_limit_status === 'limit_up').length;
  const broken = rows.filter(r => r.today_limit_status === 'broken').length;
  const down = rows.filter(r => r.today_limit_status === 'limit_down').length;
  const returns = rows.map(r => `${Number(r.today_ret_pct).toFixed(2)}%`).join('、');
  return `上一交易日涨停原因与本方向同名的样本${rows.length}条，今日涨停${up}条、炸板${broken}条、跌停${down}条，收益截面为${returns}；这只是同名样本反馈，不代表方向全体。`;
}

function stageFor(d) {
  const up = d.event_counts.limit_up;
  const broken = d.event_counts.broken;
  const down = d.event_counts.limit_down;
  if (d.theme === PRIMARY) return '延续候选';
  if (up === 0 || down > 0) return '无法确认';
  if (broken > 0 && broken >= up) return '分歧';
  if (d.max_board >= 2 && up >= 2) return '延续候选';
  if (d.max_board >= 2 && up === 1) return '无法确认';
  if (d.max_board === 1 && up >= 2) return '启动候选';
  if (up === 1) return '热点候选';
  return '无法确认';
}

function relationFor(d) {
  const up = d.event_counts.limit_up;
  const broken = d.event_counts.broken;
  const down = d.event_counts.limit_down;
  if (d.theme === PRIMARY) return 'LEADS';
  if (d.theme === '石油化工' || d.theme === '油服工程') return 'CONFIRMS';
  if (up === 0 || down > 0 || broken > up) return 'WEAKENS';
  if (up === 1) return 'ISOLATED';
  if (oilCluster.has(d.theme) || d.theme === '电网设备' || d.theme === '稀有金属') return 'FOLLOWS';
  return 'FOLLOWS';
}

function pathStatusFor(d) {
  if (d.theme === PRIMARY) return 'PRIMARY';
  if (competitors.has(d.theme)) return 'COMPETITOR';
  if (d.event_counts.limit_up === 0) return 'REJECTED';
  if (d.event_counts.limit_up === 1 && (d.event_counts.broken > 0 || d.max_board >= 2)) return 'REJECTED';
  return 'OBSERVATION';
}

function peersFor(theme) {
  return [PRIMARY, '石油化工', '油服工程', '电网设备', '稀有金属', '黄金概念']
    .filter((x, i, a) => x !== theme && a.indexOf(x) === i)
    .slice(0, 4);
}

function inferenceFor(d, stage, relation, pathStatus) {
  const up = d.event_counts.limit_up;
  const broken = d.event_counts.broken;
  const down = d.event_counts.limit_down;
  const out = [];
  if (d.theme === PRIMARY) {
    out.push('按逐层淘汰，方向不是单票：既有3板高度，又有4家当日首板扩散，且事件集合成交承载高于石油化工；因此作为盘后相对优先路径候选，但不等于主流确认或主升。');
    out.push('方向缺少2板连接层且有2家炸板，说明高度与低位之间仍有断层和失败反馈；当前功能是验证高度能否带动低位晋级，而非直接给出执行买点。');
  } else if (d.theme === '石油化工') {
    out.push('有1家2板连接5家首板，且油服工程、油气开采、天然气等相邻注册方向同步出现涨停，构成最强的跨方向响应竞争组。');
    out.push('但本方向最高仅2板、另有2家炸板；在先比较高度的层级上暂落后于商业航天3板，保留为主要竞争方向。');
  } else if (d.theme === '油服工程') {
    out.push('9家均为当日首板且无炸板，形成清晰的同日起步启动队列，并与石油化工等油气相关方向相互确认。');
    out.push('由于只有当日首板爆发、没有2板或更高晋级层，按逐层淘汰不能仅凭涨停家数超过商业航天，当前只作为强竞争启动池。');
  } else if (d.theme === '电网设备') {
    out.push('2家2板与1家首板构成小型延续梯队，且无事件失败，结构质量好于纯首板方向。');
    out.push('但高度止于2板、事件规模和成交承载较商业航天低，当前为次级竞争方向。');
  } else if (d.theme === '稀有金属') {
    out.push('2家同处2板且无炸板，昨日同名买方样本亦有延续反馈，显示晋级层有一致响应。');
    out.push('缺少首板扩散，方向更像中位晋级组，暂不足以越过商业航天的3板加首板结构。');
  } else if (up === 0) {
    out.push(`事件集合没有涨停，仅记录炸板${broken}家、跌停${down}家，失败反馈明确，不能进入主路径比较的存活组。`);
  } else if (up === 1 && d.max_board >= 2) {
    out.push(`虽有${d.max_board}板高度，但仅一只涨停、无同方向首板扩散，先按单票结构排除，不能用高度直接宣布方向成立。`);
  } else if (up === 1) {
    out.push('仅一只首板，属于孤立热点事实；没有真实同方向竞争组和梯队，不能据此确认启动或主路径。');
  } else if (d.max_board === 1) {
    out.push(`共有${up}家首板，属于当日启动队列；尚无晋级层，需先验证次日晋级，不能因单日数量自动判为主路径。`);
  } else {
    out.push(`方向已出现${d.max_board}板层并有${up}家涨停，具备一定延续结构，但高度、扩散或承载尚未超过商业航天。`);
  }
  if (broken > 0 && d.theme !== PRIMARY && d.theme !== '石油化工') {
    out.push(`同时有${broken}家炸板，失败原因只能记为未知；无完整委托流，不能断言主动或被动撤单。`);
  }
  if (down > 0) out.push(`方向内有${down}家跌停，构成明确负面反馈；但缺历史账本，不能把个案直接外推为全市场退潮。`);
  out.push(`与市场的关系评为${relation}，路径状态为${pathStatus}；该判断只描述当日横向关系。`);
  return out;
}

function gapsFor(d) {
  const buyer = sameNameBuyerText(d.theme);
  const gaps = [
    '昨日状态账本日期为2026-01-05，并非2026-02-27前一交易日，无法迁移方向历史阶段。',
    '非涨停题材成员映射为BLOCKED_DATA，数据不足，无法判断板块指数与完整方向内部响应。',
    '分钟线与逐笔成交缺失，数据不足，无法判断分时主动性、修复先后和炸板委托原因。',
    '公告与热点上下文为BLOCKED_DATA，数据不足，无法验证催化持续性。'
  ];
  if (buyer) gaps.push('昨日买方反馈仅覆盖同名涨停原因样本，不能替代方向全部持有者反馈。');
  else gaps.push('上一交易日买方反馈中无与本方向名称直接匹配的样本，数据不足，无法判断方向昨日参与者溢价。');
  return gaps;
}

const direction_evaluations = directions.map(d => {
  const stage = stageFor(d);
  const relation = relationFor(d);
  const pathStatus = pathStatusFor(d);
  const buyerText = sameNameBuyerText(d.theme);
  const observed = [
    `当日事件集合：涨停${d.event_counts.limit_up}家、炸板${d.event_counts.broken}家、跌停${d.event_counts.limit_down}家；梯队为${ladderText(d)}，最高${d.max_board}板，首板${d.n_first_board}家；已知事件成交额${moneyText(d.turnover.value_yuan)}。`
  ];
  if (buyerText) observed.push(buyerText);
  const support = [d.fact_id];
  if (buyerText) support.push(ENV_PREV);
  const counter = [];
  if (d.event_counts.broken > 0 || d.event_counts.limit_down > 0 || d.event_counts.limit_up <= 1 || d.n_first_board === 0) counter.push(d.fact_id);
  return {
    theme: d.theme,
    direction_fact_id: d.fact_id,
    stage,
    market_relation: relation,
    path_status: pathStatus,
    observed_facts: observed,
    inferences: inferenceFor(d, stage, relation, pathStatus),
    supporting_fact_ids: support,
    counter_fact_ids: counter,
    competitors: peersFor(d.theme),
    data_gaps: gapsFor(d)
  };
});

const result = {
  as_of: facts.as_of,
  environment: {
    status: 'DATA_INSUFFICIENT',
    reasoning: [
      '先按[ENV_MAIN_TREND]检查环境：当日涨停84家、跌停4家，昨日75只涨停股中43只为正反馈、32只为负反馈，说明短线局部承接仍在；但全市场上涨1142家、下跌4265家，强势事件与普遍下跌明显背离，不能确认主流主升。',
      '梯队为64家首板、18家二板、2家三板，最高仅3板；首板占主导且方向分散，既不能仅凭涨停家数定义主流，也不足以证明轮动已经完成。',
      '按[ENV_DECLINE]检查反面：普跌与32家炸板是偏弱截面，但仍有84家涨停、仅4家跌停且昨日买方正反馈多于负反馈，缺少高标连续跌停等事实，因此不能确认系统性退潮。',
      '按[ENV_REGIME_SWITCH]检查切换：缺少2026-02-27的正式环境与方向账本，无法证明旧核心带动衰减、新方向接力及资金功能迁移，不能声称切换完成。',
      '因此环境状态为DATA_INSUFFICIENT：当日表现是“全市场广度偏弱、短线涨停与晋级局部偏强”的分裂截面。该环境结论与次日条件计划的相对优先路径分层处理。',
      '遵守[DISC_NO_HINDSIGHT]与[DISC_NO_FIXED_SCORE]：只使用收盘前事实，不用固定总分，也不把涨停数量、成交额或个案形态推广为统一阈值。'
    ],
    supporting_fact_ids: [ENV_BREADTH, ENV_LADDER, ENV_PREV],
    counter_fact_ids: [ENV_BREADTH, ENV_LADDER, ENV_CONTEXT],
    migrated_from: null,
    tomorrow_checks: [
      '补建2026-02-27正式环境与方向账本，验证当前分裂截面是延续、轮动还是切换。',
      '观察全市场上涨家数能否改善，同时跌停与炸板是否继续扩散。',
      '观察商业航天3板高度、低位首板和大成交承载能否形成非孤立晋级。',
      '观察石油化工2板加首板梯队与油服工程首板池能否继续晋级并维持跨方向响应。',
      '补齐板块指数、非涨停成员、分钟线、逐笔成交、公告和热点数据；缺失前相关主动性与催化判断保持“数据不足，无法判断”。'
    ]
  },
  direction_evaluations,
  primary_path: {
    status: 'SELECTED',
    theme: PRIMARY,
    direction_fact_id: 'F-20260302-DIR-C3440C60D4',
    selection_logic: [
      'facts.path_comparison_contract表明65个方向的当日最低比较字段齐全，因此可做相对选择，不使用BLOCKED_DATA。',
      '第一层先排单票：玉柴合作虽有3板但只有一只涨停；多只单票2板方向也无扩散，不能与完整方向结构等同。',
      '第二层再排只有当日爆发的启动队列：油服工程9家均为首板，数量最多但尚无晋级层；黄金概念只有首板且6家炸板，均不能仅凭单日数量胜出。',
      '第三层比较高度与梯队：商业航天有1家3板和4家首板，石油化工为1家2板加5家首板，电网设备为2家2板加1家首板，稀有金属为2家2板且无首板；商业航天先在高度层拉开差异。',
      '第四层看扩散与承载：商业航天并非单票，保有4家首板且事件集合成交额约241.96亿元；石油化工约158.63亿元，电网设备与稀有金属更低。成交额只作同日承载证据，不设固定阈值。',
      '昨日买方反馈中，商业航天同名样本一只由2板晋级3板、另一只收跌，反馈混合；石油化工同名样本一只晋级2板。该层进入风险与取消条件，但不足以抹掉商业航天在高度层已建立的相对优先级。',
      '因此SELECTED仅表示盘后相对优先候选，方向阶段降级为“延续候选”；缺少前日账本、板块指数、完整扩散和分时主动性，不能写成MAINSTREAM_CONFIRMED、主升或超级主流。'
    ],
    supporting_fact_ids: ['F-20260302-DIR-C3440C60D4', ENV_PREV, ENV_LADDER],
    counter_fact_ids: ['F-20260302-DIR-C3440C60D4', ENV_BREADTH, ENV_CONTEXT],
    competitor_themes: ['石油化工', '油服工程', '电网设备', '稀有金属', '黄金概念'],
    cancel_conditions: [
      '商业航天3板高度失去晋级或价格承接，同时4家首板次日无晋级，方向退化为高位单票或单日脉冲。',
      '商业航天炸板与负反馈继续扩散，且板块指数、容量和非涨停成员补数后不响应。',
      '石油化工完成更高板晋级并维持5家首板扩散，或油服工程首板池形成明确晋级层，而商业航天结构不延续。',
      '电网设备或稀有金属的2板组继续晋级并补出首板扩散、大成交承载，形成新的真实竞争优势。',
      '分钟线、逐笔成交或公告催化补齐后出现明确负面事实；当前这些数据不足，无法判断。'
    ]
  },
  nodes: [
    {
      node_type: 'MAINSTREAM_CONFIRMATION_OBSERVATION',
      anchor_date: '2026-03-02',
      theme: '商业航天',
      trigger_facts: [
        '商业航天当日有1家3板、4家首板、5家涨停和2家炸板，事件集合成交额约241.96亿元。',
        '上一交易日商业航天同名涨停原因样本两条，今日一条晋级涨停、一条收跌，买方反馈并不一致。'
      ],
      trigger_fact_ids: ['F-20260302-DIR-C3440C60D4', ENV_PREV],
      method_reasoning: [
        '按[NODE_MAINSTREAM_CONFIRM]，主流确认需要板块指数、先锋和容量共同转强。当前方向只有高度与首板扩散的事件事实，板块指数和非涨停成员映射缺失，不能确认节点。',
        '当前功能是“主路径候选的主流确认观察”：进入事件为2026-03-02商业航天在全方向比较中形成3板高度加4家首板；退出条件为高度断裂且低位不晋级，或补齐数据后显示板块与容量不跟。',
        '由于没有匹配任何G1—G12生成器的完整前提，本节点generator保持null，只观察方向关系，不生成股票买点。'
      ],
      generator: null,
      candidate_ids: [],
      confirm: [
        '板块指数连续走强，3板高度与低位晋级非孤立，同时出现可验证的大成交承载和方向带动。',
        '昨日参与者反馈继续改善，且2家炸板未扩散为方向性失败。'
      ],
      cancel: [
        '只有高位单票推进，首板与非涨停成员不响应。',
        '高度断裂、低位无晋级，或竞争方向先形成更完整的高度与扩散。'
      ]
    },
    {
      node_type: 'SAME_DAY_FIRST_BOARD_COMPETITION',
      anchor_date: '2026-03-02',
      theme: '油服工程',
      trigger_facts: [
        '油服工程当日9家涨停全部为首板、无炸板和跌停，起算日明确为2026-03-02共同首板日。'
      ],
      trigger_fact_ids: ['F-20260302-DIR-4E5BED5B7D'],
      method_reasoning: [
        '该方向满足[G08_UNIQUENESS]的入口：同一方向、同一共同首板日、功能相近的启动队列；没有把3板、2板与首板混合梯队重置起算日。',
        '当前功能是“同期启动竞争池”：进入事件为2026-03-02九家共同首板；退出条件为次日无人晋级、油气相关方向整体不响应，或后续新对手主动胜出。',
        'G8此时只生成观察池，不确认唯一载体；缺少分钟线与逐笔成交，数据不足，无法判断队列内部主动性，candidate_ids保持空数组。'
      ],
      generator: 'G8',
      candidate_ids: [],
      confirm: [
        '后续交易日出现真实晋级竞争，并由换手、容量、方向响应和次日任务形成阶段唯一性。',
        '油服工程与石油化工、油气开采等相关方向保持共振，而非九只首板同时退化。'
      ],
      cancel: [
        '共同首板池次日无有效晋级或仅剩孤立消息票。',
        '油气相关方向整体失去响应，或新竞争方向以更完整梯队主动胜出。'
      ]
    }
  ],
  data_gaps: [
    '2026-02-27正式环境与方向状态账本缺失；现有yesterday_state.json日期为2026-01-05，不能迁移。',
    '完整非涨停题材成员与板块指数映射缺失，数据不足，无法确认主流、容量带动和方向内部普遍响应。',
    '分钟线与逐笔成交缺失，数据不足，无法判断竞价后主动性、分时修复、承接先后及炸板委托原因。',
    '公告与热点数据为BLOCKED_DATA，数据不足，无法验证催化来源和持续性。',
    '风险提示、特别监控和停牌数据为BLOCKED_DATA；监管精确数值阈值未核验，不计算异动距离，也不声称仍有监管空间。',
    'rules.md未提供统一的轮动环境规则，只能用现有环境规则做排除式判断，不能自行创造固定阈值。'
  ]
};

fs.mkdirSync(path.join(process.cwd(), 'output'), { recursive: true });
fs.writeFileSync(path.join(process.cwd(), 'output', 'result.json'), JSON.stringify(result, null, 2) + '\n');
