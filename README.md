# ResearchLoop Evo

**Evidence-grounded Autonomous Research & Self-Evolving Agent**
基于文献证据与实验验证的自进化科研智能体。

用户输入一个具体研究方向，系统自主完成：文献检索 → 结构化整理 → 研究空白提出 → 反证检索 →
人工确认 → 最小实验设计与真实执行 → 独立评测 → 失败轨迹提炼 Skill → 回放评测 → 版本晋升决策 → 研究档案。

> **当前进度：18 步端到端垂直切片已可运行**（Phase 1–6 全部完成，见 `TASKS.md`）。
> 两条完整流程已对 OpenAlex / Crossref / arXiv **真实跑通**，其中一条全程通过浏览器 UI 驱动。
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
| 没有 LLM Key 就不伪装成 LLM Agent | 服务端未配置 Provider 时走确定性规则，UI 与报告显式标注 **Heuristic Mode** |
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
- LLM：**默认零模型调用**。抽取、空白发现、失败诊断、候选提议全部为确定性规则；
  LLM 为默认关闭的可选扩展，读取服务端环境变量，输出必须过 Pydantic 校验并保留原文证据，Key 不进前端

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
cd backend && python -m pytest -q                              # 235 离线测试，不联网
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
│   │   ├── main.py            FastAPI 入口、lifespan、6 个路由注册
│   │   ├── config.py          超时/限流/缓存/API 开关
│   │   ├── models/            paper schemas gap experiment skill evolution workflow
│   │   ├── api/               routes_literature / gaps / experiments / skills / evolution / workflows
│   │   ├── services/
│   │   │   ├── sources/       openalex.py crossref.py arxiv.py
│   │   │   ├── http.py        共享客户端：限流 + 重试 + 缓存 + 代理校验
│   │   │   ├── normalize.py   原始记录 → Paper（含 provenance）
│   │   │   ├── dedupe.py      DOI 归一 + 标题相似度去重
│   │   │   ├── rank.py        相关性与综述优先排序（稳定排序）
│   │   │   ├── extract.py     证据化启发式抽取（10 个字段）
│   │   │   ├── classify.py    有序方法分类
│   │   │   ├── pipeline.py    检索编排（多源合并/失败聚合）
│   │   │   ├── gap.py         多论文比较 → 6 类空白 + 反证检索
│   │   │   ├── benchmark.py   DOI 元数据核验 + 按主题分组切分
│   │   │   ├── experiment.py  两臂真实执行 + 原始快照
│   │   │   ├── evaluator.py   独立评测 + 晋升门禁（纯 Python）
│   │   │   ├── evolution.py   经验收集 / 6 类诊断 / 候选提议
│   │   │   ├── promotion.py   版本激活与回滚守卫
│   │   │   ├── workflow.py    18 步编排器（可恢复、有界、人工门禁）
│   │   │   ├── report.py      7 节研究报告（事实/作者观点/系统推断分离）
│   │   │   └── export.py      CSV / JSON 导出
│   │   └── storage/store.py   SQLite 持久化（含 workflows 表）
│   └── tests/                 14 个测试模块，235 离线 + 3 真实 API
└── frontend/src/
    ├── pages/                 11 个真实页面（无占位页）
    │   Dashboard Discovery Library Matrix Report ResearchGap
    │   ExperimentLab EvolutionLab SkillRegistry Workflow Dossier
    ├── components/            experiment/ workflow/ 共享 UI
    └── api/  lib/  types/
```

## 5. Phase 路线图

| Phase | 内容 | 状态 |
| --- | --- | --- |
| 1 | Literature Discovery：检索、去重、结构化、对比矩阵、报告 | ✅ 完成并实测 |
| 2 | Research Gap：多论文比较的 6 类空白 + 真实反证检索 + 人工确认 | ✅ 完成并实测 |
| 3 | Experiment Lab：冻结协议、两臂真实执行、独立 Evaluator、原始快照 | ✅ 完成并实测 |
| 4 | Evolution Lab：经验收集、6 类失败诊断、限额候选提议、回放评测 | ✅ 完成并实测 |
| 5 | Skill Registry：不可覆盖版本、Active 读取、六条晋升门禁、回滚守卫 | ✅ 完成并实测 |
| 6 | 18 步 Workflow + Research Dossier：可恢复编排、两个人工门禁、档案 | ✅ 完成并实测 |
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
- **LLM 提议器未在真实 Provider 上运行**：服务端未配置 Key，实测走确定性回退并显式标注原因；
  LLM 路径的校验、限额与失败回退由离线测试覆盖。
- **回滚正向路径仅有离线测试覆盖**：真实库中无 archived 版本（晋升始终被正确拒绝）。
- 详见 `CREDIT_BUDGET.md` 关于额度与部署能力的核实结果，`TASKS.md` 关于逐项验收与真实运行记录。