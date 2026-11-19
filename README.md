# ResearchLoop Evo

**Evidence-grounded Autonomous Research & Self-Evolving Agent**
基于文献证据与实验验证的自进化科研智能体。

用户输入一个具体研究方向，系统自主完成：文献检索 → 结构化整理 → 研究空白提出 → 反证检索 →
人工确认 → 最小实验设计与真实执行 → 独立评测 → 失败轨迹提炼 Skill → 回放评测 → 版本晋升决策 → 研究档案。

> **当前进度：18 步端到端垂直切片已可运行**（Phase 1–7 全部完成，见 `TASKS.md`）。
> 两条完整流程已对 OpenAlex / Crossref / arXiv **真实跑通**，其中一条全程通过浏览器 UI 驱动。
>
> **Phase 8（多智能体 Gap Discovery）已用真实 DeepSeek 模型跑通一次完整 7 阶段管线**（2026-11-18）：
> 30 篇真实论文 → 20 张 Evidence Card → 5 个候选 Gap → 5 次独立 Critic 评审 →
> 每条 Gap 5 个检索词 × OpenAlex/Crossref/arXiv 的真实反证检索 → Python 17 项独立校验 →
> 门禁把 **5 条全部判为 `needs_human_review`，没有自动接受任何一条**（真实 prior art 冲突、评审分数不足、
> 支持论文数不足）。真实用量 34 / 60 次调用、104,511 tokens；Key 未进入数据库、日志、前端或 Git。
> **仍为 NOT RUN 的部分**：人工确认（5 条 Gap 等你决定）与 18 步 Workflow 的真实 LLM 全链路（角色预算已用尽），
> 见 `TASKS.md` 的真实性表。
>
> **但自进化实验尚未通过最终验收**：基准参考 DOI 已真实核验、**未经人工确认**，
> 因此 Reference Coverage@K 保持 `null`（不是 0），晋升门禁关闭，档案验收状态如实写为
> `awaiting_reference_set`。交付的是**可运行的进化流程 + 待标注基准**，不是"已验证的性能提升"。

---

## 1. 真实性承诺

这个项目的第一原则是**可追溯**，宁可留空也不编造：

| 承诺 | 实现方式 |
| --- | --- |
| 论文、作者、DOI、年份、摘要全部来自真实 API | OpenAlex / Crossref / arXiv 实时检索，代码中无任何硬编码论文列表 |
| 未获取到的字段必须标记缺失 | `evidence_status = unknown`，绝不猜测填充 |
| 只读了摘要不能假装读了全文 | 每个抽取字段带 `evidence_source` 与原文 `evidence_span`；报告 caveats 明写"未获取任何全文" |
| 没有 LLM Key 就不伪装成 LLM Agent | 服务端未配置 Provider 时显式返回 **LLM_NOT_CONFIGURED**，走确定性规则并记录回退原因，绝不伪造 LLM 结果 |
| LLM 不能自己证明自己正确 | LLM 只提出候选与评审意见；论文是否存在、证据是否逐字、是否重复计数、反证是否检索成功、最终门禁全部由 **独立 Python** 判定 |
| LLM 调用可审计且不泄密 | 每次调用记录 role/model/request_id/latency/状态/token 与 prompt·response 的 **hash**；不存 prompt 正文，Key 只来自服务端环境变量，不进数据库、日志、前端、Git |
| 模型花的钱有上限 | `RLE_LLM_MAX_CALLS` 总额 + 每角色预算；超额停止并置 `awaiting_budget`，已完成产物保留，resume 不重复付费；同论文同 prompt 版本命中缓存免费 |
| 网络失败要显示真实错误 | 后端原样返回 HTTP 状态与原因，前端展示错误条与重试按钮，不回退到假数据 |
| 没有假按钮和假动画 | 11 个页面全部绑定真实接口；进化候选、评测数字、晋升拒绝原因均来自已落库记录 |
| 空白不能只凭一篇论文的 Future Work | 每个候选由**多篇论文的方法与实验范围比较**得出，并自动对三个来源做反证检索 |
| 没找到反证 ≠ 问题不存在 | 只表述"当前检索范围内未发现"，并记录检索来源、请求数、被拒条数 |
| 置信度不冒充统计概率 | 只有有依据的 `Low / Medium / High` 标签 + 文字理由 |
| 覆盖率不是领域绝对 Recall | 只针对**人工确认的参考集合**计算；无确认集合时为 `null` |
| 评测不依赖 Agent 自我评价 | 独立纯 Python Evaluator 从**原始响应快照**重算，记录 `recomputed_from` |
| 缓存不隐藏成本 | 成本按 `api_request_count + cache_hits` 计，请求比与上限检查都用这个总数 |
| 图表不用静态数字 | 所有条形/表格绑定真实计算结果；新增图表用按真实值比例绘制的 CSS 条 |

## 2. 技术栈

- 前端：React 19.3 + TypeScript 7.0 + Vite 8.3 + Tailwind CSS v4 + Recharts 3.10 + React Router 7.18
- 后端：Python 3.13 + FastAPI + Pydantic v2 + httpx
- 数据：SQLite（标准库 `sqlite3`）+ 文件型 HTTP 缓存 + 原始响应 JSON 快照；无 Redis、无向量库、无 Docker、无微服务
- LLM：**默认零模型调用**。Paper 字段抽取、分类、规则式空白发现、失败诊断、评测、报告全部为确定性规则。
  可选的 **多智能体 Gap Pipeline**（Planner / Literature Analyst / Gap Analyst / Gap Critic 四角色 +
  Python 筛选、反证检索、独立验证与门禁）读取服务端环境变量，输出必须过 Pydantic 校验，
  `evidence_span` 必须能在送入模型的摘要中逐字定位，否则丢弃并记入 `rejected_fields`；
  Evidence Card 单独存表，**不回写 Paper 字段**，Key 不进前端

## 3. 快速开始

```bash
# 1) 后端
cd ResearchLoop-Evo/backend
python -m venv .venv
source .venv/Scripts/activate        # Windows Git Bash
pip install -r requirements.txt
cp .env.example .env                 # 建议填 mailto=<你的邮箱> 进入各 API 的礼貌池
uvicorn app.main:app --reload --port 8000

# 2) 前端（另一个终端）
cd ResearchLoop-Evo/frontend
npm install
npm run dev                          # http://localhost:5173
```

### 演示路径（推荐）

1. 打开 **18-Step Workflow** → 填写研究主题 → **创建流程**（只建状态，不自动执行）。
2. 点 **连续执行到人工门禁** → 真实检索 12 篇文献、抽取字段、建矩阵、发现空白、对三源做反证检索，
   然后停在第 8 步等待人工。
3. 在 **人工确认门禁** 填写决策人 → 对某个候选点 **接受**（门禁关闭并继续）。
   也可先去 **Research Gap** 页读支撑证据与反证原文再决定。
4. 再点 **连续执行到人工门禁** → 形成假设、冻结实验协议、真实执行基线与候选两臂、
   独立评测、失败诊断、技能变异、回放评测，停在第 17 步。
5. 在 **晋升 / 回滚** 面板查看门禁的逐条拒绝原因 → 选择 **尝试晋升候选**（会被真实拒绝）
   或 **保持现状** → 流程走到第 18 步。
6. 打开 **Research Dossier** 查看完整档案：验收状态、7 节报告（事实 / 作者观点 / 系统推断分色）、
   空白与反证、实验对比、进化与版本决策。

单步执行、失败原地重试、回退到任意先前步骤都在同一页面；回退会清空该步及其后的输出与 context，
已打开过 holdout 的流程拒绝回退。

### 测试与构建

```bash
cd backend && python -m pytest -q                              # 301 离线测试，不联网
RLE_LIVE_TESTS=1 python -m pytest tests/test_live_sources.py -v  # 3 个真实 API 测试（强制绕过缓存）
cd frontend && npm run build                                   # tsc -b && vite build
```

离线测试把检索、DOI 核验、反证检索全部 patch 在**使用点**，用真实启发式抽取器构造响应，
因此跑的是与线上相同的记录形状。真实 API 测试单独运行，且每次调用都 `refresh=True`——
被缓存服务的"真实测试"什么都验证不了。

## 4. 目录结构

```
ResearchLoop-Evo/
├── README.md  PRD.md  ARCHITECTURE.md  CREDIT_BUDGET.md  TASKS.md
├── backend/
│   ├── app/
│   │   ├── main.py            FastAPI 入口、lifespan、8 个路由注册
│   │   ├── config.py          超时/限流/缓存/API 开关/LLM 预算与门禁阈值
│   │   ├── models/            paper schemas gap gap_pipeline llm experiment skill evolution workflow
│   │   ├── api/               routes_literature / gaps / experiments / skills / evolution / workflows / gap_pipeline(含 llm)
│   │   ├── services/
│   │   │   ├── sources/       openalex.py crossref.py arxiv.py
│   │   │   ├── http.py        共享客户端：限流 + 重试 + 缓存 + 代理校验
│   │   │   ├── normalize.py   原始记录 → Paper（含 provenance）
│   │   │   ├── dedupe.py      DOI 归一 + 标题相似度去重
│   │   │   ├── rank.py        相关性与综述优先排序（稳定排序）
│   │   │   ├── extract.py     证据化启发式抽取（10 个字段）
│   │   │   ├── classify.py    有序方法分类
│   │   │   ├── pipeline.py    检索编排（多源合并/失败聚合）
│   │   │   ├── gap.py         多论文比较 → 9 类空白 + 反证检索
│   │   │   ├── llm.py         唯一 LLM Provider：审计 + 预算 + 缓存 + redaction
│   │   │   ├── gap_agents.py  Planner / Analyst / Gap Analyst / Critic 四角色 + 逐字校验
│   │   │   ├── gap_pipeline.py 七阶段编排（落盘、可恢复、预算停止）
│   │   │   ├── gap_validator.py 独立 Python 验证 + 可配置最终门禁
│   │   │   ├── benchmark.py   DOI 元数据核验 + 按主题分组切分
│   │   │   ├── experiment.py  两臂真实执行 + 原始快照
│   │   │   ├── evaluator.py   独立评测 + 晋升门禁（纯 Python）
│   │   │   ├── evolution.py   经验收集 / 6 类诊断 / 候选提议
│   │   │   ├── promotion.py   版本激活与回滚守卫
│   │   │   ├── workflow.py    18 步编排器（可恢复、有界、人工门禁）
│   │   │   ├── report.py      7 节研究报告（事实/作者观点/系统推断分离）
│   │   │   └── export.py      CSV / JSON 导出
│   │   └── storage/store.py   SQLite 持久化（17 张表，含 llm_calls / llm_cache / evidence_cards / gap_pipelines）
│   └── tests/                 18 个测试模块，301 离线 + 3 真实 API
└── frontend/src/
    ├── pages/                 11 个真实页面（无占位页）
    │   Dashboard Discovery Library Matrix Report ResearchGap
    │   ExperimentLab EvolutionLab SkillRegistry Workflow Dossier
    ├── components/            experiment/ workflow/ gap/ 共享 UI
    │   gap/EvidenceChain · EvidenceCards · PipelinePanel（完整证据链）
    └── api/  lib/  types/
```

## 5. Phase 路线图

| Phase | 内容 | 状态 |
| --- | --- | --- |
| 1 | Literature Discovery：检索、去重、结构化、对比矩阵、报告 | ✅ 完成并实测 |
| 2 | Research Gap：多论文比较的 9 类空白 + 真实反证检索 + 人工确认 | ✅ 完成并实测 |
| 3 | Experiment Lab：冻结协议、两臂真实执行、独立 Evaluator、原始快照 | ✅ 完成并实测 |
| 4 | Evolution Lab：经验收集、6 类失败诊断、限额候选提议、回放评测 | ✅ 完成并实测 |
| 5 | Skill Registry：不可覆盖版本、Active 读取、六条晋升门禁、回滚守卫 | ✅ 完成并实测 |
| 6 | 18 步 Workflow + Research Dossier：可恢复编排、两个人工门禁、档案 | ✅ 完成并实测 |
| 7 | P5 测试、构建、文档与验收边界（离线测试与真实 API 测试分离） | ✅ 完成 |
| 8 | 多智能体 Gap Discovery：四角色 LLM + Evidence Card + Critic + 独立 Python 门禁 + 预算/缓存/审计 + 证据链 UI | ✅ 代码、离线 E2E 与**真实 DeepSeek 7 阶段管线均已跑通**；5 条候选全部被门禁挡在 `needs_human_review` |
| — | 人工确认参考集合 → 锁定候选 → holdout 终检 → 真实晋升 | ⬜ **待人工标注，未完成** |

## 6. 已知限制

- **自进化实验尚未通过最终验收**：参考 DOI 已真实核验但未经人工确认，覆盖率保持 `null`，
  晋升门禁关闭。真实运行中人工尝试晋升被**正确拒绝**（6 条原因），Active 版本始终为 v1。
- **派生参考集合存在自指重叠风险**：workflow 的基准参考来自它自己的检索结果，基线可能本来就覆盖它们。
  这不是独立金标准，只是供人工复核的种子；该风险在 case notes、步骤输出与档案中原文披露。
- **最小预算下变异区分度不足**：两条真实流程的 baseline 与 candidate 都检索到 12 篇（`top_k=12`、
  单查询 3 来源）。替换一个词未改变最终保留集合——这是真实结果，说明需要更大的参考集合与更宽的 case。
- **Recharts 图表未能像素级视觉验收**：应用内浏览器视口塌陷（`innerWidth === 0`），
  `ResponsiveContainer` 不挂载 SVG surface，`take_screenshot` 返回 `NATIVE_BROWSER_VIEWPORT_UNAVAILABLE`。
  数据绑定已用真实 API 数据核对，控制台无错误；新增页面改用 CSS 比例条 + 表格绕开该问题。
  **结论：数据绑定为真，旧图像素渲染未验证**，需在正常浏览器中复核。
- **arXiv 限流严格**：已做 ≥3 秒间隔与失败降级；真实数据中 arXiv 对最终 top-k 的贡献常为 0，
  由 `source_coverage_insufficient` 诊断如实报告，不夸大修复效果。
- **Crossref 会返回组件记录**（如 `10.7717/peerj-cs.2926/table-4` "Table 4: ..."），
  这类 DOI 真实存在但不是论文；下游去重与排序按普通记录处理，人工确认参考集时应剔除。
- **Crossref `/works` 默认不返回摘要**，摘要主要来自 OpenAlex 与 arXiv；缺失时显示"摘要缺失"。
- **未抓取任何付费全文**：10 个抽取字段全部来自元数据与合法开放摘要，`evidence_source` 一律为 `abstract`。
- **真实 LLM E2E 已完成 7 阶段管线，但未覆盖 18 步 Workflow**（2026-11-18）：DeepSeek
  （`RLE_LLM_ENABLED=1`、`RLE_LLM_BASE_URL=https://api.deepseek.com`、`RLE_LLM_MODEL=deepseek-flash`、
  `RLE_LLM_MAX_CALLS=60`）真实运行：30 篇论文（29 篇有摘要）、20 张 Evidence Card（259.4s）、
  5 个候选 Gap、5 次 Critic、5×5 个反证查询（每条 3 家来源）、Python 17 项校验 × 5 条 →
  **5 条全部 `needs_human_review`**：真实 prior art 冲突 10/1/1/4 篇、Critic 证据分 2–3/5、
  2 条支持论文不足 3 篇。真实用量 **34/60 次调用、104,511 tokens、1 次 schema 拒绝（未缓存）**。
  - **模型名是实测定下来的**：`GET /models` 返回 `deepseek-flash` 与 `deepseek-v4-pro`；
    `deepseek-chat` 在该账号不存在——先前"`deepseek-flash` 非公开模型名"的判断是错的，已更正。
  - **发现并修复一个真实缺陷**：Gap Analyst 把依据写进 `novelty_risk` 枚举（`"MEDIUM: …"`）导致 schema 拒绝。
    修法是新增 `novelty_rationale` 字段并改 prompt/输出契约，**保持枚举严格拒绝**（不静默截断字符串）。
  - **真实检索限制**：OpenAlex 对 `agent memory management` 返回 HTTP 429（3 次重试后如实记录为 source error）；
    Crossref/arXiv 该组查询贡献 0 篇。topic-only 检索会召回硬件/神经科学"memory"论文，因此本轮用**已声明的**
    LLM 专用关键词 + `year_from=2022`，没有改写排序器掩盖问题。
  - **NOT RUN**：18 步 Workflow 的真实 LLM 全链路（角色预算已用尽：planner 2/2、gap 2/2、critic 5/5、
    counter 5/5，总额 34/60）与真实人工确认（5 条 Gap 等你的决定，系统不代签）。
  - 四角色编排、逐字 span 校验、Critic 隔离、预算停止与 resume、缓存复用、审计与 redaction、独立门禁
    由 **304 个离线测试**覆盖（另有 3 个 live 测试默认跳过），LLM 回复来自只替换网络接缝的
    `FakeLLMProvider`——**Fake 结果只存在于测试库，绝不写入真实 run / experiment / promotion 证据**。
- **LLM 证据链 UI 已用真实数据核对**：Research Gap 页渲染 5 条真实 Gap 的完整五段证据链
  （含"提出者自评依据"、Critic 四项整数分、Python 逐项校验、门禁原因、真实 prior art 链接）；
  Dossier 页对旧档案（生成于 `llm` 审计字段之前）给出如实回退并在浏览器中修复过一次真实崩溃。
- **回滚正向路径仅有离线测试覆盖**：真实库中无 archived 版本（晋升始终被正确拒绝）。
- **跨 run 的论文归属只保留最后一次**：`papers` 以 `paper_id` 为主键并 upsert `run_id`，
  同一篇论文被两条流程检索到时按 `run_id` 过滤 Library 会少显示（实测 12 篇中少 2 篇）。
  workflow 自身的 `context["paper_ids"]` 完整，矩阵/空白/实验/档案不受影响。
  正确修法是加 `run_papers` 关联表，属数据迁移，留待下一轮。
- 详见 `CREDIT_BUDGET.md` 关于额度与部署能力的核实结果，`TASKS.md` 关于逐项验收与真实运行记录。