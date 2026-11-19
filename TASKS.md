# TASKS — ResearchLoop Evo

状态标记：`[x]` 已完成并验证 · `[~]` 代码完成待验证 · `[ ]` 未开始
本文件是唯一进度真相来源；每阶段结束时更新，不并行推进多个 Phase。

## Phase 0 · 环境与能力（已完成）

- [x] 检查工作区，确认不改动旧项目 `labtrace`
- [x] 确认本机工具链：node v24.14.1 / npm 11.11.0 / python 3.13.9 / git 2.53
- [x] 官方文档核实 Sites、Sites DB/Storage、Cloud Agents 计费与 SSE、Credits 规则
- [x] 实测学术 API 连通性：OpenAlex 200、Crossref 200、arXiv 429（限流，需 ≥3s）
- [x] 架构决策：本地 FastAPI + SQLite，前端 React/Vite，Phase 1 零 LLM 零 Cloud Agent

## Phase 1 · Literature Discovery（本阶段）

### 1.1 文档基线
- [x] README.md
- [x] PRD.md
- [x] ARCHITECTURE.md
- [x] CREDIT_BUDGET.md
- [x] TASKS.md

### 1.2 后端
- [x] 项目骨架、依赖清单、`.env.example`（含 mailto、限速、超时、TTL、开关）
- [x] Paper / FieldEvidence / 请求响应 Pydantic 模型 + 证据一致性校验
- [x] `http.py`：令牌桶限速、有界重试、文件缓存、真实错误对象
- [x] `sources/openalex.py`：search / filter / 摘要倒排还原 / review 识别
- [x] `sources/crossref.py`：query.bibliographic / DOI / select 字段
- [x] `sources/arxiv.py`：Atom 解析 + ≥3s 间隔 + 429 降级
- [x] `normalize.py`：三源统一 → Paper（含 `source_url`、`missing_fields`）
- [x] `dedupe.py`：DOI 归一 + 标题 token/序列相似度合并
- [x] `rank.py`：相关度 + 关键词覆盖 + 年份近因 + 综述加分
- [x] `extract.py`：摘要切句 + 线索词分类 + `evidence_span` 逐字保留
- [x] `pipeline.py`：多关键词×多来源编排、失败聚合、缓存命中统计
- [x] `store.py`：SQLite（projects / runs / papers / paper_edits）
- [x] `report.py`：7 节报告 + 事实 / 作者观点 / 系统推断分离
- [x] `export.py`：矩阵 CSV（BOM，Excel 中文安全）与 JSON
- [x] API 路由：search / runs / papers / detail / 字段人工补充 / matrix / export / report / health
- [x] 未来模块路由返回 501（gaps / experiments / evolve / skills）
- [x] 离线单元测试（归一、去重、抽取、pipeline、API）
- [x] 可选真实 API 冒烟测试（默认跳过，`RLE_LIVE_TESTS=1` 开启）

### 1.3 前端
- [x] Vite + React + TS + Tailwind + Recharts + Router 配置
- [x] 侧边导航：5 实页 + 4 占位（带 Phase 标记）
- [x] Research Dashboard：run 概览、年份分布、来源占比、最近检索
- [x] Literature Discovery：输入表单、关键词扩展、来源勾选、进度与真实错误
- [x] Literature Library：过滤（年份/来源/综述/证据状态/搜索）、分页、详情抽屉、人工补充
- [x] Literature Matrix：勾选生成、证据展开、单元格编辑、CSV/JSON 导出
- [x] Research Report：7 节报告与三类内容分离展示
- [x] 占位页调用真实 501 接口并显示"未实现 + 所属 Phase"
- [x] `npm run build` 通过

### 1.4 收尾
- [x] 后端 pytest 全绿 + 前端 build 成功
- [x] 真实一次端到端检索验证（本机 API 实测）
- [ ] 用户检查与确认

## Phase 2 · Research Gap（已完成，commit 82abba3）

- [x] `ResearchGap` 12 字段契约，Pydantic 强制"至少两篇不同论文 + 逐字证据"
- [x] 6 类空白检测（method / evaluation / generalization / reliability / efficiency / reproducibility）
- [x] 禁止单篇 Future Work 推断空白；必须跨论文比较方法与实验范围
- [x] 每个候选自动对 OpenAlex / Crossref / arXiv 构造反证检索，命中则降级为 Low
- [x] 未找到反证只表述"当前检索范围内未发现"，绝不表述"不存在"
- [x] 置信度为有依据的 Low / Medium / High 标签 + rationale，非统计概率
- [x] 默认 `needs_human_review`；人工接受 / 拒绝 / 改写落库
- [x] 新增 `agent_architecture` / `memory_strategy` / `skill_strategy` 抽取字段
- [x] 无 LLM Provider，全链路显式标注 Heuristic Mode
- [ ] 可选 LLM 抽取增强（未启用；需先出额度预算并等确认，见 CREDIT_BUDGET §5）

## Phase 3 · Experiment Lab（后端 + 前端已完成并实测）

- [x] 单一 Agent-Evolution 模板；假设标注 `under_test`，非既定结论
- [x] `BenchmarkCase` + Development / Validation / Holdout 按 topic 分组切分（防泄漏）
- [x] 参考 DOI 经 Crossref / OpenAlex 真实核验；人工 `confirmed_by` 才成为 Ground Truth
- [x] 未确认参考集 → `awaiting_reference_set`，允许检索、禁止晋升，不编造覆盖率
- [x] 独立纯 Python Evaluator：Coverage@K / Missed Refs / API 查询数 / 唯一论文数 / 执行时间
- [x] 成本口径含缓存命中（`api_request_count + cache_hits`），暖缓存不能掩盖额外检索
- [x] 冻结协议：来源 / 年份 / Top-K / 请求上限对两臂一致；Candidate 不得改评测与基准
- [x] 原始响应快照落盘 + `POST /verify` 从快照独立重算并比对
- [x] Holdout 在候选锁定前关闭，锁定后仅允许一次
- [x] 六条晋升规则实现于 `promotion_blockers`，门禁未通过时列出全部真实原因
- [x] Experiment Lab 页面：基准 / Skill / 设计 / 执行 / 复核 / 历史对比
- [ ] 图表像素级视觉验收（受环境限制，见"已知限制"）

## 已知限制

- **Recharts 图表未能视觉验收**：应用内浏览器视口塌陷（`window.innerWidth === 0`、
  `innerHeight === 0`，`take_screenshot` 返回 `NATIVE_BROWSER_VIEWPORT_UNAVAILABLE`），
  `ResponsiveContainer` 测得宽度 0，因此不挂载 SVG surface。已尝试 3 次（等待、
  强制父容器 1000px、读取 React fiber）均无法在此环境取得非零尺寸。
  控制台无任何错误；图表数据绑定已用真实 API 数据核对：
  development / validation 各两臂，baseline `api_queries=3`、candidate `api_queries=6`、
  `unique_papers=20`，全部来自已落库的 run 记录，无静态数字。
  **结论：数据绑定为真，像素渲染未验证**，需在正常浏览器中复核。
- **自进化实验尚未通过最终验收**：3 个基准案例的参考 DOI 已真实核验但**未经人工确认**，
  覆盖率保持 `null`，晋升门禁关闭。交付的是可运行流程 + 待标注基准。
- **真实数据发现**：6 次真实检索中 arXiv 对最终 top-k 的贡献均为 0，OpenAlex 主导。
  该现象由 `source_coverage_insufficient` 诊断如实报告；由于 OpenAlex 已排在首位，
  系统同时说明"仅重排来源无法弥补这部分覆盖"，不夸大修复效果。
- **回滚正向路径仅有离线测试覆盖**：真实库中尚无 archived 版本（晋升始终被正确拒绝），
  因此无法在真实数据上演示一次成功回滚。回滚守卫（拒绝从未 active 的版本）已实测。
- **LLM 提议器未在真实 Provider 上运行**：服务端未配置 Key，实测走确定性回退并显式标注原因。
  LLM 路径的校验、限额与失败回退由离线测试覆盖。
- **派生参考集合存在自指重叠风险**：workflow 的基准参考 DOI 来自它自己的检索结果，
  因此基线可能本来就覆盖它们。这不是独立金标准，只是供人工复核的种子；
  该风险在 case notes、步骤输出与档案中原文披露。要得到有意义的覆盖率，
  必须由人工确认或**替换**为独立来源的参考集合。
- **两条真实流程的 baseline 与 candidate 检索到的论文数相同（各 12 篇）**：
  在 `top_k=12` 且单查询 3 来源的预算下，替换一个词并未改变最终保留集合。
  这是真实结果，不是图表造假；它说明当前最小预算下变异的区分度不足，
  需要更大的参考集合与更宽的 case 才能测出覆盖率差异。
- **workflow 内无法演示成功晋升**：晋升需要人工确认参考集 + 锁定候选 + 执行 holdout，
  而 holdout 在结构上不由 workflow 打开。完整晋升路径需在 Experiment Lab 中人工完成，
  目前只有离线测试覆盖（真实库中无 archived 版本）。

## Phase 4 · Evolution Lab（已完成并实测）

- [x] 经验收集：从已落库 ExperimentRun + 原始快照还原真实试验信号
- [x] 6 类失败诊断，每条附触发它的真实数字；无信号则不产生诊断
- [x] 诊断不把 API 传输失败归咎于 prompt；预算截断不算 API 失败
- [x] 统一 `CandidateProposer`：默认确定性，可选限额 LLM（1 次/轮，Pydantic 校验 + 预算钳制）
- [x] 每轮最多 3 个候选，记录父版本 / 变异描述 / 来源试验 / 改动组件 / 创建时间
- [x] 候选查询数由**实测基线成本 × 1.5** 推导，不会一出生就超预算
- [x] 变异只使用 development 试验；validation / holdout 的参考标题与年份不外泄
- [x] 缺证据时拒绝编造变异，并写明拒绝原因（如无确认参考集）
- [x] 需要改动冻结协议的诊断只报告、不产生候选
- [x] `source_priority` 与 `search_filters` 变为真实生效：前者置换冻结来源集合影响
      稳定排序的并列裁决，后者只能收窄冻结年份窗口
- [x] Evolution Lab 页面：协议选择 / 轮次历史 / 预算推导 / 诊断 / 被拒绝变异 / 候选 / 真实经验

## Phase 5 · Skill Registry & Promotion（已完成并实测）

- [x] 版本不可覆盖；新 Run 读取 Active Version；历史 Run 保留自身 Skill Snapshot
- [x] `POST /api/skills/evaluate`：真实执行两臂并由独立 Evaluator 打分
- [x] `POST /api/skills/promote`：六条门禁全过才激活，否则 409 + 全部真实原因
- [x] `POST /api/skills/rollback`：只能回到曾经 active 的版本，绕过门禁但不声称提升
- [x] Skill Registry 页面：可进化边界 / 版本总览 / 快照与事件 / 晋升决策 / 变更历史
- [x] 晋升被拒时前端完整展示服务端返回的逐条原因
- [ ] 正式部署决策与访问范围（本轮不做）

## Phase 6 · 18 步端到端 Workflow（已完成并实测）

- [x] `STEP_SEQUENCE` 固定 18 步，模型校验器拒绝任何乱序或缺步的状态
- [x] 每一步调用**已拥有该能力的真实服务**，记录它实际产出的 id 与数字，
      不存在"只在 UI 上标记完成"的步骤
- [x] 状态每次转移后 upsert 落盘（`workflows` 表），重启后从准确的 pending 步继续
- [x] 失败保留真实异常文本，可原地重试（`attempts` 递增）或受守卫的回退重跑
- [x] 回退清空该步及其后所有步骤的输出**与它们拥有的 context 键**，
      避免重跑时静默复用过期的人工批准
- [x] 已打开过 holdout 的流程拒绝回退（一次性终检不可被反复搜索）
- [x] 执行有界：`max_steps` 1..18，遇人工门禁或失败立即停止
- [x] 两个人工门禁：`human_approval`（空白接受/拒绝）与 `promotion_decision`
- [x] 跨流程批准被拒绝：只能批准本流程自己产出的 gap
- [x] 鸡生蛋问题的解法：`_gap_seed_candidate` 以被接受空白的支撑论文标题词频
      产生首个候选，复用与 P3 提议器相同的预算推导与单模板替换；
      替换词必须**同时**不在空白问题与该 case 的 topic/query 措辞中，否则不做无意义变异
- [x] 基准 case 由真实方法类派生出 3 个**不同**子主题，`assign_splits` 因此产出全部三个 split
- [x] 参考 DOI 经真实 `verify_doi` 核验；全部核验失败则拒绝建基准，不编造 Ground Truth
- [x] 派生参考的自指风险在 case notes 与步骤输出中**原文披露**，不隐藏
- [x] 独立评测从**原始快照**重算每一 run，快照缺失时回退到已存记录并写明 `recomputed_from`
- [x] 回放为每个新候选创建**新的冻结协议**（`created_by="workflow-replay"`），
      基线、参考集合、来源、年份、Top-K、上限与评分公式完全不变
- [x] Holdout 在结构上不可由 workflow 打开（只跑 development / validation）
- [x] 晋升被拒是**被记录的结果**而非杀死流程的异常，档案因此能如实写出验收状态
- [x] 前端 `/workflow`：启动面板 / 流程列表 / 执行控制 / 回退选择 / 两个人工门禁面板 /
      18 步可展开轨迹（每步真实输入输出 + 原始 JSON 兜底）
- [x] 前端 `/dossier`：验收状态横幅 / 总览 / 假设 / 7 节报告（事实·作者观点·系统推断分色）/
      空白与反证表 / 实验对比条 / 进化与版本决策
- [x] 新增图表一律用**按真实数值比例绘制的 CSS 条 + 表格**，绕开零视口下
      Recharts 不挂载 surface 的环境问题；覆盖率为 `null` 时显示 `—` 而非 0
- [x] 51 个离线 workflow 测试；全量 **235 passed, 3 skipped**
- [x] 真实 API 实测两条完整流程（见下）

### 真实运行记录（Live API，非 Mock）

| 流程 | 主题 | 文献 | 真实请求 / 缓存命中 | 来源失败 | 空白 | 反证论文 | 进化候选 | 验收状态 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `wf_824946f92a37` | agent experience learning | 12 | 14 / 0 | 0 | 6 | 30 | 1（2 项如实跳过） | `awaiting_reference_set` |
| `wf_44b4549be7ab` | LLM agent memory mechanisms | 12 | 15 / 3 | 0 | 4 | 17 | 0（3 项如实跳过） | `awaiting_reference_set` |

> 成本口径：`total_api_queries = requests_made + cache_hits`，因此第二条流程的文献检索
> 总查询数是 **18**，不是 15。缓存命中照样计入成本，不让候选看起来更省预算。
> 同理，`wf_824946f92a37` 被接受空白 `gap_18dcbce49f34` 的反证检索是**缓存服务**的
> （`requests_made=0, cache_hits=3`），该事实原样记录在 `counter_search_scope` 中。

- 第一条流程完整走完 18 步：人工接受 `gap_18dcbce49f34`（generalization / Medium / 4 篇支撑），
  种子候选把 `{query}` 替换为 `{query} agentic`（真实新词），
  两臂各 3 请求 / 12 篇，覆盖率 `null`，门禁 6 条原因，
  **人工尝试晋升被独立门禁拒绝**（`outcome=refused`，Active 仍为 v1），档案如实写出。
- 第二条流程全程**通过浏览器 UI** 驱动：表单创建 → 连续执行到门禁 → 填写决策人后接受空白
  （门禁自动关闭）→ 执行到晋升门禁 → 选择"保持现状"（`outcome=kept`）→ 18/18 完成。
- 第二条流程本轮 0 候选：三项变异分别因"无确认参考集，拒绝编造词汇"、
  "主题词已全部出现在已执行查询中"、"来源优先级已等于实测贡献顺序，无意义变异不提出"被跳过。
- 浏览器控制台无任何错误；`tsc -b && vite build` 通过。

### 真实实验与版本记录（直接查 SQLite 核对，非叙述）

- 库中累计：**22 次文献检索 / 87 篇论文 / 18 个空白 / 9 个基准 case / 5 份冻结协议 /
  20 条实验运行 / 11 个技能版本 / 6 个进化轮 / 2 条完整流程**。
- **20 条实验运行全部 `status=awaiting_reference_set`、`coverage_at_k=null`、`source_errors=0`**。
  没有任何一条计算出覆盖率，因此不存在任何"性能提升"数字。
- 两条流程的两臂对比（development / validation 各一条）：

| 协议 | 臂 | 唯一论文 | 真实请求 | 缓存命中 | 总查询 | 覆盖率 |
| --- | --- | --- | --- | --- | --- | --- |
| `spec_78bd9c84f786`（wf1） | baseline | 12 | 0 | 3 | 3 | `null` |
| `spec_78bd9c84f786`（wf1） | candidate | 12 | 3 | 0 | 3 | `null` |
| `spec_891898bbf756`（wf1 回放） | baseline / candidate | 12 / 12 | 0 / 0 | 3 / 3 | 3 / 3 | `null` |
| `spec_fe4de61c2f09`（wf2） | baseline | 12 | 3 | 0 | 3 | `null` |
| `spec_fe4de61c2f09`（wf2） | candidate | 12 | 3 | 0 | 3 | `null` |

  请求比 1.0（≤1.5× 上限），但**覆盖率无法比较**，所以门禁第 1 条无法判定为"提升"。
- 版本谱系：v1 `skillv_d6ddaef6304f`（seed，**始终 Active**）→ 10 个 candidate，
  **0 个 archived**（从未发生真实晋升，因此回滚正向路径只有离线测试覆盖）。
  wf1 种子候选 v9 把 `{query}` 变为 `{query} agentic`；进化轮 `evor_ed4a2e844430`
  产出 v10，唯一改动是 `source_priority` 由 `[openalex, crossref, arxiv]`
  置换为 `[openalex, arxiv, crossref]`（冻结来源集合不变，只动同分裁决顺序）。
  wf2 种子候选 v11 为 `{query} judge`，其进化轮 `evor_addbeb3fb204` **0 提案 / 3 项如实跳过**。
- 修复前的无意义种子候选 v8（`{query} learning`，与 case 措辞重复）作为历史记录留在注册表中，
  对应协议 `spec_a0f50d75493e` 已被回退清空；**不删除历史版本**，版本不可覆盖。
- 6 个进化轮全部 `proposer_mode=deterministic`，
  `llm_skip_reason="no LLM provider is configured on the server; the deterministic proposer ran instead"`。
- 晋升门禁真实判断（`allowed=false`，逐条原文）：
  `no human-confirmed reference set for: case_…` /
  `case_…: coverage is unavailable without confirmed references` /
  `case_…: both arms must be executed before promotion` /
  `the candidate was never locked for the final holdout check` /
  `the final holdout check has not been executed`。
  wf1 人工选择"尝试晋升" → `outcome=refused`；wf2 人工选择"保持现状" → `outcome=kept`。
  两者 Active 均为 v1。

## Phase 7 · P5 测试、构建、文档与验收边界（已完成）

### 离线测试与构建

- [x] 全量离线测试 **235 passed, 3 skipped**（14 个测试模块，检索 / DOI 核验 / 反证检索
      全部 patch 在**使用点**，不联网、不依赖外部服务）
- [x] 未删除任何既有测试，未放宽任何验收条件
- [x] `tsc -b && vite build` 通过（产物 `index-BKK6kn4L.js`，806.78 kB），
      开启 `noUnusedLocals` / `noUnusedParameters` / `verbatimModuleSyntax`

### 真实 API 测试：修掉两个"假通过"

- [x] **陷阱一：磁盘缓存服务的"真实测试"**。首次运行 3 passed 仅用 **0.11 秒**，
      `cache_hits` 非零而 `requests_made=0`——这种通过什么都没验证。
      修复：三个 live 测试全部传 `refresh=True` 强制绕过缓存
      （`refresh` 是适配器的独立参数，不来自 `TopicInput`）。
- [x] **陷阱二：Windows Proactor 事件循环亲和性**。缓存的 `httpx.AsyncClient`
      的 transport 绑定在创建它的 loop 上；pytest-asyncio 每个测试一个 loop，
      先前 loop 关闭后再拆连接会从后续测试抛出 `RuntimeError: Event loop is closed`。
      第一次修复失败：strict 模式下 async generator 用普通 `@pytest.fixture`
      **根本不会执行 teardown**。第二次修复成功：改用
      `@pytest_asyncio.fixture(autouse=True)` 调用 `close_client()`，镜像 app lifespan。
      **未改产品代码**——生产单 loop 是正确的，加 loop 探测属于为不可能场景写防御代码。
- [x] 修复后真实运行 **3 passed / 9.25 秒**，`cache_hits=0`：

| 来源 | 真实记录数 | 真实请求数 | 真实 DOI 样例 |
| --- | --- | --- | --- |
| OpenAlex | 5 | 2 | `10.1109/mnet.001.1900656` |
| Crossref | 5 | 1 | `10.32388/lx0f9e`；组件记录 `10.7717/peerj-cs.2926/table-4` |
| arXiv | 5 | 1 | `10.48550/arxiv.2209.05872` |

- [x] 新发现：**Crossref 会返回组件记录**（`10.7717/peerj-cs.2926/table-4`
      "Table 4: Smart contract vulnerability analysis."）。DOI 真实存在但不是论文，
      下游按普通记录处理；**人工确认参考集时必须剔除**。已写入 README 已知限制与 ARCHITECTURE §1。

### 截图：环境阻塞，如实记录（不伪造）

- [x] 尝试 `take_screenshot` 于 `/dossier?workflow_id=wf_824946f92a37`，返回
      `NATIVE_BROWSER_VIEWPORT_UNAVAILABLE`：
      `viewport=0x0, visible=false, attached=false, cdpAttached=true, visibilityState=hidden`。
      `window.innerWidth / innerHeight` 均为 0，因此 **Recharts `ResponsiveContainer`
      不挂载 SVG surface**，旧图无法像素级视觉验收。
- [x] **替代证据（真实、可复核）**：用 `take_snapshot` 取无障碍树 + `evaluate_script`
      读真实 DOM 文本与数值，核对 18 步轨迹、门禁逐条拒绝原因、覆盖率渲染为 `—`（不是 0）、
      档案验收状态 `awaiting_reference_set`；`list_console_messages` 无错误。
- [x] 新增页面（Workflow / Dossier）改用**按真实数值比例绘制的 CSS 条 + 表格**绕开该问题。
- [x] **结论：数据绑定为真，旧图像素渲染未验证**，需在正常浏览器中复核。
      本轮**未产出截图文件**，不把文本抓取冒充截图。

### 演示步骤（已写入 README §3，可逐步复现）

1. **18-Step Workflow** → 填研究主题 → **创建流程**（只建状态，不自动执行）
2. **连续执行到人工门禁** → 真实检索 12 篇 → 抽取 → 矩阵 → 空白 → 三源反证 → 停在第 8 步
3. 填决策人 → 对候选点 **接受**（门禁关闭并推进 1 步）；可先去 Research Gap 页读证据原文
4. **连续执行到人工门禁** → 假设 → 冻结协议 → 两臂真实执行 → 独立评测 → 诊断 → 变异 → 回放 → 停在第 17 步
5. 晋升面板读逐条拒绝原因 → **尝试晋升**（被真实拒绝）或 **保持现状** → 第 18 步
6. **Research Dossier** 看验收状态、7 节报告、空白与反证、实验对比、进化与版本决策

### 文档更新

- [x] `README.md`：进度横幅（可运行但**未通过最终验收**）、13 行真实性承诺、
      演示路径、测试命令、目录树、Phase 1–6 路线图 + 待人工标注行、11 条已知限制
- [x] `ARCHITECTURE.md` v0.6：13 节，能力核实 / 12 张表 / FieldEvidence 强制规则 /
      冻结协议 / 六条门禁 / 进化边界 / 18 步编排 / 完整 API 表（无 501）/ 非功能性设计 / 演进路径
- [x] `CREDIT_BUDGET.md`：Phase 状态表 + §4 实际消耗（**余额本机不可读，不编造**）+
      §4.1 缓存假通过陷阱 + §5 LLM 开关前成本评估（尚未启用）
- [x] `TASKS.md`：Phase 6 逐项验收 + 两条真实运行记录 + 本节

### 本轮新发现的一个数据归属问题（已定位根因，未修，如实记录）

`papers` 表以 `paper_id` 为主键，`save_paper` 用
`ON CONFLICT(paper_id) DO UPDATE SET run_id=excluded.run_id`
（[store.py:242](backend/app/storage/store.py)）。因此**同一篇论文被两条流程检索到时，
只保留最后一次的 `run_id`**：`wf_824946f92a37` 的 12 个 `paper_ids` 中有 2 篇
（`A-Mem`、`Agentic RAG Survey`）的行归属已指向后跑的 `run_1794937848428`，
按该 run_id 过滤 Library 只显示 10 篇。

- **影响范围有限**：workflow 的 `context["paper_ids"]` 保存了自己完整的 12 个 id，
  矩阵、空白、实验、档案都按 context 取数，**不受影响**；受影响的只有
  `GET /api/literature/papers?run_id=…` 这一种过滤视图。
- **正确修法**：新增 `run_papers(run_id, paper_id)` 关联表，`papers.run_id` 降级为首次来源；
  属于数据迁移，本轮 P5 范围是测试/构建/文档，**不在收尾阶段启动新的开发任务**，故留待下一轮。

### 验收边界（不可逾越）

- [x] 交付的是**可运行的进化流程 + 待标注基准**，不是"已验证的性能提升"
- [x] 无人工确认参考集 → 覆盖率 `null`（不是 0）→ 晋升门禁关闭 →
      档案 `acceptance_status = awaiting_reference_set`
- [x] **不宣称自进化实验已通过最终验收**

## Phase 8 · 证据锚定的多智能体 Gap Discovery（代码、离线 E2E 与真实 7 阶段管线均已跑通；18 步 Workflow 真实链路 = NOT RUN）

目标：把"确定性检索 + 规则式 Gap Discovery + 可选 LLM proposer"升级为
**Evidence-grounded Multi-Agent Research Gap Discovery + Counter-Evidence Verification**，
建立在既有 18 步 Workflow 与实验/评测/进化基础设施之上。原则：**LLM 提出与评审，Python 与真实检索验证**。

### 交付清单（逐项对应任务书 §22）

- [x] OpenAI-compatible LLM Provider（`services/llm.py`，唯一网络接缝 `_post`）
- [x] Research Planner Agent（多角度检索计划，Schema + Budget 校验）
- [x] Literature Analyst Agent（逐论文 Evidence Card，7 个字段全部带 span/source）
- [x] Research Gap Analyst Agent（只吃 Evidence Cards，跨论文综合 → Candidate Gap）
- [x] Gap Critic / Judge Agent（**看不到 Gap Agent 内部推理**，0~5 分 + LOW/MEDIUM/HIGH）
- [x] Python Gap Validator（`services/gap_validator.py`，12 项证据/反证检查 + 5 项 Critic 门禁 + 可配置阈值）
- [x] Counter-Evidence 真正参与验证（区分 `NO_COUNTER_EVIDENCE_FOUND` / `COUNTER_SEARCH_FAILED`）
- [x] Checkpoint / Resume（7 阶段产物落盘 `gap_pipelines.json`，resume 不重复付费）
- [x] LLM call budget（总额 `RLE_LLM_MAX_CALLS` + 每角色上限；超额 → `awaiting_budget`）
- [x] Evidence traceability（span 必须逐字命中送入模型的摘要，否则进 `rejected_fields`）
- [x] Human Gate（保留原门禁；页面展示证据链而非单一分数）
- [x] Research Gap UI（Topic → Plan → Paper Evidence → Gaps → Critique → Counter → Validation → Decision）
- [x] Unit tests / Integration tests（新增 5 个测试模块 + `tests/fakes.py`）
- [x] Build succeeds（`tsc -b && vite build`）
- [x] **真实 LLM E2E（7 阶段管线）= REAL**（2026-11-18，DeepSeek `deepseek-flash`，详见下节）
- [ ] 18 步 Workflow 的真实 LLM 全链路 + 真实人工确认 = **NOT RUN**（角色预算用尽；5 条 Gap 等人工决定）

### 真实性标注

| 项 | 标注 | 依据 |
| --- | --- | --- |
| 四角色编排、逐字 span 校验、Critic 隔离、预算停止、resume、缓存、审计 redaction、独立门禁 | **MOCK（仅测试库）** | `FakeLLMProvider` 只替换 `_post`，结果只写入 `temp_db`，绝不进真实 run/experiment/promotion |
| 真实模型 completion 调用 | **REAL = 34 次**（含 1 次 schema 拒绝），0 缓存命中 | `llm_calls` 34 行，provider `deepseek`、model `deepseek-flash`；tokens 19,655 + 84,856 = **104,511** |
| LLM Evidence Card | **REAL = 20 张**（20/20 选定论文） | 259.4 s；span 全部逐字命中摘要，`evidence_source=abstract` |
| LLM Candidate Gap | **REAL = 5 条**（evaluation×3、integration×1、method×1） | 全部 `needs_human_review`，0 条自动接受 |
| LLM Critique | **REAL = 5 次** | 四项 0–5 整数分，`recommended_action` 全为 `revise`，无百分比 |
| 真实反证检索（LLM 生成查询） | **REAL = 17 次请求 / 5 条 Gap** | 5 个查询/条 × 3 家来源；48 篇检索结果，16 篇被判为 prior art |
| Python 独立校验 | **REAL = 17 项 × 5 条** | 逐字命中、无重复计数、反证检索完成等硬检查全部 PASS |
| 真实论文 | **REAL = 87 + 30 篇**（22 + 1 个 run） | 全部来自 OpenAlex / Crossref / arXiv，无硬编码 |
| 规则式空白 | **REAL = 18 条**（accepted 3 / needs_human_review 12 / rejected 3） | 3 条 accepted 带真实人工决策备注 |
| 18 步 Workflow 两条完整流程 | **REAL**（规则式路径） | 均走到 `research_dossier`；晋升被 6 条门禁正确拒绝，Active 仍为 v1 |
| 18 步 Workflow 的真实 LLM 全链路 / 真实人工确认 | **NOT RUN** | 角色预算用尽；5 条真实 Gap 等人工决定 |

### 真实 E2E 记录（2026-11-18）

- **Provider / 模型**：DeepSeek，`https://api.deepseek.com`，`deepseek-flash`
  （`GET /models` 实测返回 `deepseek-flash`、`deepseek-v4-pro`；该账号**没有** `deepseek-chat`）。
- **管线**：`gpipe_2f3cdb1cb3bd`（真实 run `run_1794985534678`），7 阶段全部 `completed`。
- **检索输入（已声明，未调整排序器）**：topic `LLM agent memory mechanisms`；
  关键词 `LLM agent memory` / `large language model agent memory` / `agent memory management` /
  `long-term memory for LLM agents` / `llm` / `agent`；`year_from=2022`；三源；26 次真实请求、2 次缓存命中、40.7 s。
  结果 **30 篇、29 篇有摘要、2023–2026，全部来自 OpenAlex**；
  OpenAlex 对 `agent memory management` 返回 **HTTP 429**（3 次尝试）并如实记入 `source_errors`，
  Crossref / arXiv 对该组查询贡献 0 篇。20 篇中有 6 篇标题为 survey/review
  （Provider 元数据 `is_review` 全为 false，因此**不宣称**来源标注为综述）。
- **用量**：34 / 60 次真实调用（planner 2、analyst 20、gap 2、critic 5、counter 5），1 次失败（schema 拒绝，未缓存），
  104,511 tokens；Key 未进入数据库 / 日志 / 前端 / Git。
- **Gap 结论（REAL，且系统没有给自己开门）**：5 条全部 `needs_human_review`：
  - `gap_…_0`：支持论文 2 < 3；Critic 证据分 2/5、跨论文支持 2/5 → 不通过
  - `gap_…_1`：真实 prior art 冲突 **10 篇** + novelty_risk HIGH（门禁上限 MEDIUM）→ 不通过
  - `gap_…_2` / `_3`：prior art 各 1 篇、Critic 2/5 → 不通过
  - `gap_…_4`：支持论文 2 < 3、prior art 4 篇、跨论文支持 2/5 → 不通过
  - 反证状态：1 条 `NO_COUNTER_EVIDENCE_FOUND`、4 条 `COUNTER_EVIDENCE_FOUND`；0 条被当作检索失败
- **审计产物**：`backend/var/real_e2e_dossier.json`（服务端返回的 pipeline + cards + gaps + llm_calls + usage）
  经 `var/verify_real_dossier.py` 对照 §19 十问逐项核查：**136 项断言全部通过**（含每条 span 逐字命中摘要、
  DOI 存在、三源范围、Critic 0–5、17 项 Python 校验、无自动接受、payload 内无凭据）。

### 真实 LLM 排障记录（已解决）

- 第一次 `GET /models` 为 **HTTP 401**：用户先给的是 36 字符 UUID（DeepSeek Key 应为 `sk-` 开头）；
  换有效 `sk-` Key 后 **HTTP 200**。401 期间未发起任何 completion，未消耗额度。
- 曾误判 `deepseek-flash` 不是公开模型名——实为错误，已按 `/models` 结果更正（见上）。
- 角色预算全局计数：第二轮真实管线在 `research_planner`（1/1）处停止为 `awaiting_budget`；
  经用户同意把 planner 提到 2 后 resume 同一管线，已完成的 20 张卡片没有重付费。
- 真实运行暴露并修复的缺陷：Gap Analyst 把依据写进 `novelty_risk`（`"MEDIUM: …"`）→ schema 拒绝、
  未缓存。**没有放宽校验**：新增 `novelty_rationale` 字段、改 prompt 与输出契约，
  并加 2 个离线回归测试（prose 仍被拒绝；依据随标签落库）。
- 本机 `NO_PROXY` 含 `[::1]` 会让默认 httpx 抛 `InvalidURL: Invalid port`；
  `services/llm.py` 客户端用 `trust_env=False`，文献源侧用 `build_proxy_mounts()` 校验，均不受影响。
- `.env` 末尾是用户覆盖块，与模板同名重复；`load_dotenv()` **后值生效**：
  `ENABLED=1` / `BASE_URL=https://api.deepseek.com` / `MODEL=deepseek-flash` / `MAX_CALLS=60` / planner 2。

### 凭据处置记录

- 发现用户把真实 Key 追加进了 **Git 跟踪的 `backend/.env.example`**。核查确认**从未进入任何 commit**、暂存区为空。
- 已把凭据块移入 **gitignored `backend/.env`**（写入过程不回显 Key），模板恢复为纯文档。
- 复扫用**字节精确匹配**（Python 读取 `.env` 最后一个有效值）覆盖：整棵工作树（含 `dist/`、`var/` 缓存与快照）、
  `git ls-files` 全部跟踪文件、`git log -p --all`、`git diff HEAD`、SQLite 每张表每个文本列 →
  **命中数全为 0，Key 仅存在于 `backend/.env`**。
  （早先用 shell `grep -F "$KEY"` 的扫描因 `.env` 重复键使变量含换行、退化为空模式而无效，已作废并重做。）
- 持久化的错误字符串同样过 `_redact`，避免 Key 经异常消息落库。

### 本轮其它修正

- `models/gap.py`：旧记录缺 `counter_status` 却持有真实反证 → 派生为 `COUNTER_EVIDENCE_FOUND`，
  不再把已完成的检索误报为 `NOT_RUN`；workflow 第 7 步据此跳过已检索空白。
- `tests/conftest.py`：新增 autouse `_offline_env`，剥离本机 `.env` 的 `RLE_LLM_*` / `RLE_GATE_*`，
  保证离线测试在配置了真实 Key 的机器上仍然确定。
- 删除临时验证产物 `frontend/vite.config.verify.ts` 与临时服务；未触碰用户既有 8000/5173 服务。
- README / ARCHITECTURE 更正：删除 `RemoteLLMExtractor` 的过度声明，补 17 张表、四角色、
  审计/预算/缓存语义与 NOT RUN 边界。（真实 E2E 跑通后，这三处边界已改写为 REAL 记录，见上。）

## 明确不做（避免范围蔓延）

- ❌ 向量数据库、Redis、Kubernetes、微服务拆分
- ❌ 付费全文抓取或绕过订阅墙
- ❌ 假数据、假按钮、假执行动画
- ❌ 未经确认的自动部署与 Cloud Agent 长任务
