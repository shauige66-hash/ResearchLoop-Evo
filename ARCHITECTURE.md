# ARCHITECTURE — ResearchLoop Evo

版本：v0.7（证据锚定的多智能体 Gap Discovery + 反证验证）　日期：2026-11-18

## 1. 能力核实结论（决定架构的前置事实）

核实方式：官方文档 + 本机 HTTP 实测。**未启动 Cloud Agent，未部署，未产生额外额度消耗。**

| 能力 | 核实结果 | 对架构的影响 |
| --- | --- | --- |
| Qoder Sites | 个人付费档（含 Pro）可用；提供站点产物 + Database + Storage + Secrets + Function，站点可调用 Cloud Agents；Free 仅静态 | 前端可托管；**但没有自由常驻 Python 运行时**，FastAPI 后端不能作为长期在线服务部署在 Sites |
| Sites Database / Storage | 付费档可用，本期未启用 | 若需跨设备共享研究项目再启用 |
| Sites 免费期 | 官方标注"上线限免，有使用上限，超限会临时限制创建/访问" | 不作为核心依赖，正式部署推迟到用户确认 |
| Cloud Agents | 可用；Session 状态机 `idle/running/rescheduling/terminated`；SSE 支持 `Last-Event-ID` 续传；**沙箱按 running 秒计费**（2026-08-10 起），模型调用按 token 折算；个人 PAT 官方标注仅适合测试/PoC | **全程未使用**。真实实验执行改由本地 FastAPI 直接调用公开学术 API 完成，零沙箱费用 |
| Credits 规则 | Pro 2000/月，当期清零不结转；失败请求不扣费；**Efficient 档限时 0.0x（付费用户选择即不扣 Credits）**；Credit Pack $20/1500、有效期 1 个月 | 见 `CREDIT_BUDGET.md` 的开发策略 |
| OpenAlex | 本机实测 HTTP 200；`abstract_inverted_index` 部分记录缺失 | 主力来源：元数据 + 摘要 |
| Crossref | 本机实测 HTTP 200；`/works` 结果默认不含 `abstract`；会返回组件记录（如 `/table-4`） | 补充 DOI/元数据校验与二次来源；组件 DOI 需人工剔除 |
| arXiv | 本机实测 `429 Rate exceeded`（需 ≥3s 间隔） | 可选来源，默认开启但严格限速 + 失败降级 |
| 学术出版商全文 | 未抓取 | 合规红线：不绕过付费墙，`fulltext` 证据只允许人工录入 |

## 2. 总体架构

```
┌──────────────────── Browser (React 19 SPA, :5173) ────────────────────┐
│ Dashboard · Discovery · Library · Matrix · Report · ResearchGap       │
│ ExperimentLab · EvolutionLab · SkillRegistry · Workflow · Dossier     │
│                        11 个真实页面，无占位页                          │
└──────────────────────────────┬────────────────────────────────────────┘
                               │ REST/JSON (Vite dev proxy → :8000)
┌──────────────────────────────▼────────────────────────────────────────┐
│                FastAPI 后端 (Python 3.13, 本地运行)                    │
│                                                                       │
│  api/  routes_literature · gaps · experiments · skills · evolution    │
│        routes_workflows · gap_pipeline(含 /api/llm)                   │
│        参数校验 · 运行记录 · 错误聚合                                  │
│                                                                       │
│  services/workflow.py    18 步编排器（有界推进 · 落盘恢复 · 人工门禁）  │
│    │                                                                  │
│    ├─ pipeline.py        多关键词×多来源编排                           │
│    │    ├─ sources/      openalex · crossref · arxiv                  │
│    │    ├─ http.py       令牌桶限速 + 有界重试 + 文件缓存 + 代理校验    │
│    │    ├─ normalize.py  RawRecord → Paper (+provenance)              │
│    │    ├─ dedupe.py     DOI 归一 · 标题相似度合并                     │
│    │    ├─ rank.py       相关性 + 综述优先 + 年份衰减（稳定排序）       │
│    │    └─ extract.py    摘要证据化启发式抽取（10 字段）                │
│    ├─ classify.py        有序方法分类                                  │
│    ├─ gap.py             多论文比较 → 9 类空白 + 三源反证检索           │
│    ├─ llm.py             唯一 OpenAI-compatible Provider：审计/预算/缓存 │
│    ├─ gap_agents.py      四角色 prompt + 逐字 span 校验                  │
│    ├─ gap_pipeline.py    七阶段编排（落盘 · 可恢复 · 预算停止）          │
│    ├─ gap_validator.py   独立 Python 验证 + 可配置最终门禁               │
│    ├─ benchmark.py       DOI 元数据核验 + 按主题分组切分                │
│    ├─ experiment.py      两臂真实执行 + 原始响应快照                    │
│    ├─ evaluator.py       独立评测 + 六条晋升门禁（纯 Python）           │
│    ├─ evolution.py       经验收集 / 6 类诊断 / 限额候选提议             │
│    ├─ promotion.py       版本激活与回滚守卫                            │
│    ├─ report.py          7 节报告（事实/作者观点/系统推断分离）         │
│    └─ export.py          CSV / JSON                                   │
│                                                                       │
│  storage/store.py        SQLite 17 张表（见 §3.3）                     │
│  var/experiments/*.json  每次实验运行的原始响应快照                     │
└──────────────────────────────┬────────────────────────────────────────┘
                               │ HTTPS
                  OpenAlex · Crossref · arXiv（公开学术 API）
                  + 可选：服务端环境变量配置的 OpenAI-compatible LLM endpoint
```

**默认零 LLM 调用**：抽取、分类、规则式空白发现、失败诊断、候选提议、评测、报告都是确定性代码，
可单测、可复现、零模型额度消耗。配置 Provider 后，LLM 只负责**跨论文理解与提出候选**，
验证仍由 Python 与真实文献检索完成——**不让 LLM 自己证明自己正确**（§6）。
未配置时显式返回 `LLM_NOT_CONFIGURED`，绝不伪造 LLM 运行结果。

## 3. 数据模型

### 3.1 FieldEvidence（证据单元，整个项目的核心设计）

```python
class FieldEvidence(BaseModel):
    value: str | None = None
    evidence_source: Literal["abstract", "fulltext", "manual", "model_inference", "none"]
    evidence_span: str | None = None    # 支撑该字段的原文片段（逐字摘录）
    source_url: str | None = None       # 片段来自哪个可访问记录页
    confidence: Literal["high", "medium", "low", "unknown"]
    extraction_method: Literal["heuristic", "llm", "manual"]
    evidence_status: Literal["grounded", "unknown"]
    updated_at: str | None = None
```

规则（Pydantic `model_validator` 强制）：
- `evidence_source == "none"` → value 必须为空；反之非 none 必须有非空 value。
- `evidence_source ∈ {abstract, model_inference}` → **必须有逐字 `evidence_span`**。
  这是"不许假装读过"的技术强制。
- `fulltext` / `manual` 只能由用户编辑写入（API 层拒绝外部来源提交 `fulltext`）。
- `is_known` 是 Python `@property`，**不参与序列化**；前端判断依据是 `evidence_status == "grounded"`。

### 3.2 Paper

10 个抽取字段（`EXTRACTED_FIELDS`）：
`research_problem, method, agent_architecture, memory_strategy, skill_strategy,
dataset, evaluation_metrics, findings, limitations, future_work`

书目字段：`paper_id, title, authors, publication_year, venue, doi, abstract, source,
source_url, oa_url, document_type, is_review, citation_count, relevance_score,
language, retrieved_at, run_id, duplicate_of`。

派生字段：
- `evidence_status`：`metadata_only` / `abstract_grounded` / `partially_missing` /
  `fulltext_grounded` / `unknown`，由 10 个字段的证据自动推导。
- `missing_fields`：同样自动推导，不手填。
- `extraction_mode`：来自 `models/paper.py` 的单一常量 `EXTRACTION_MODE = "heuristic"`。
  LLM 抽取器必须翻转该常量并把每个字段的 `extraction_method` 设为 `"llm"`，
  UI 才不会宣称一个没跑过的模式。

### 3.3 SQLite 表（17 张，全部 `CREATE TABLE IF NOT EXISTS` + JSON blob）

```
projects(id, topic, field, created_at, updated_at)
runs(id, project_id, request_json, created_at, finished_at, status, source_errors_json, paper_count)
papers(paper_id, run_id, project_id, publication_year, doi, source, is_review, evidence_status, json, retrieved_at)
paper_edits(paper_id, field, value_json, evidence_source, evidence_span, updated_at)

gaps(gap_id, run_id, gap_type, status, confidence_label, title, json, created_at, updated_at)
gap_reviews(id, gap_id, status, human_note, reviewed_at)

benchmark_cases(case_id, topic, split, reference_status, json, created_at)
experiment_specs(spec_id, template_id, json, created_at)
experiment_runs(run_id, spec_id, case_id, arm, split, skill_version_id, status, json, started_at, finished_at)

skill_versions(version_id, skill_id, version_number, status, parent_version, json, created_at)
skill_events(id, version_id, event, detail, created_at)
evolution_rounds(round_id, spec_id, parent_version_id, json, created_at)

workflows(workflow_id, topic, status, current_step, json, created_at, updated_at)

llm_calls(request_id, agent_role, provider, model, status, pipeline_id, paper_id,
          prompt_version, prompt_hash, response_hash, latency_ms,
          prompt_tokens, completion_tokens, total_tokens, error, created_at)
llm_cache(cache_key, agent_role, model, prompt_version, content, created_at)
evidence_cards(paper_id, prompt_version, pipeline_id, abstract_hash, json, created_at)
gap_pipelines(pipeline_id, topic, run_id, workflow_id, status, current_stage, json, created_at, updated_at)
```

索引：`papers(run_id/project_id/publication_year/doi)`、`gaps(run_id/status)`、
`benchmark_cases(split)`、`experiment_runs(spec_id/case_id)`、
`skill_versions(skill_id,status)`、`evolution_rounds(spec_id)`、
`llm_calls(agent_role/pipeline_id)`、`evidence_cards(pipeline_id)`、`gap_pipelines(workflow_id)`。

`llm_calls` 只存 hash 与计量，**没有 prompt/response 正文列，也没有 key 列**。
`evidence_cards` 主键是 `(paper_id, prompt_version)`，因此同一篇论文在同一 prompt 版本下
只付一次费；复用时卡片保留**最初付费的 pipeline_id**。

注意：`experiment_runs.split` 是**独立列**，不在序列化 JSON 中；
`EvaluationReport` 的字段名是 `coverage_at_k`（不是 `reference_coverage_at_k`）。
`papers` 以 `paper_id` 为主键并 upsert，`run_id` 会被最后一次检索覆盖——
跨 run 共享论文的归属因此是**有损**的（见 §13），workflow 用自己的 `context["paper_ids"]` 取数。

### 3.4 ResearchGap（12 个字段，缺一不可）

```
gap_id, title, description, gap_type, supporting_papers, supporting_evidence,
counter_evidence, closest_related_work, unresolved_question, experimentability,
confidence_label, status
```

- `gap_type` ∈ method / evaluation / generalization / reliability / efficiency / reproducibility /
  coverage / contradiction / integration（后三类由 LLM pipeline 引入，旧六类保持不变）。
- `status` 默认 `needs_human_review`；只有人工接受后才进入实验设计。
- `confidence_label` 只有 Low / Medium / High + `confidence_rationale` 文字理由，**不是概率**。
- `counter_search_scope` 记录来源、请求数、缓存命中、检索到的条数、被判定"未回应该主张"的条数
  与接受规则；没找到反证时只表述"当前检索范围内未发现"。
- `counter_status` ∈ NOT_RUN / COUNTER_EVIDENCE_FOUND / NO_COUNTER_EVIDENCE_FOUND /
  COUNTER_SEARCH_FAILED。**检索失败绝不等于没有反证**；升级前写入的旧记录若已存有真实反证，
  读取时由模型校验器推导为 COUNTER_EVIDENCE_FOUND，不再误报 NOT_RUN。
- LLM pipeline 追加的字段（`discovery_mode`、`pipeline_id`、`candidate`、`critique`、
  `validation`、`gate`、`prior_art`、`novelty_risk`）是**纯增量**：规则式空白留空，
  下游任何逻辑都不依赖它们。`novelty_risk` 只有 LOW / MEDIUM / HIGH，不出现概率数字。

### 3.5 BenchmarkCase 与两步 Ground Truth

```
case_id, topic, query, reference_dois, split, source, verified_by, created_at, notes, references
```

- `split` ∈ development / validation / holdout，**按主题分组**切分（同主题不跨 split，防泄漏）。
- 第一步：`verify_doi` 对 Crossref/OpenAlex 做**元数据核验**，证明 DOI 真实存在。
- 第二步：只有人工 `confirmed_by` 才把它变成参考集合。
- `confirmed_dois` / `reference_status` 是**派生属性**，不是可写字段。
- 无确认集合 → 评测状态 `awaiting_reference_set`，覆盖率 `null`，允许检索但**禁止晋升**。

### 3.6 SkillVersion 与可进化边界

唯一可进化组件：`literature_search_strategy`
（`query_templates, domain_synonyms, keyword_expansion_rules, source_priority,
search_filters, retrieval_budget`）。

不可变：Evaluator 代码与公式、Benchmark 参考 DOI 与 split、API 来源集合、预算上限。

- 版本**不可覆盖**（`save_skill_version` 对已存在 version_id 抛 ValueError）。
- 新 Run 读取当前 Active Version；历史 Run 保留自身 `skill_snapshot`。
- `created_by` ∈ seed / human / proposer；`status` ∈ active / candidate / archived / rejected。

## 4. 检索与去重流程

```
1. 关键词集合 = 用户关键词 ∪ 主题切分扩展（标注 origin="system_expanded"）
2. 对 (keyword × source) 组合并发但有界，每来源独立令牌桶
3. 每个来源返回 RawRecord → normalize → Paper（含 source_url）
4. 去重：
   a. DOI 归一（去前缀、小写）→ 完全相同即合并，保留信息最全记录，其余 duplicate_of 指向
   b. 无 DOI 时标题归一 → token Jaccard 与 SequenceMatcher 双指标
   c. 合并时字段并集：摘要缺失方可用另一来源补齐，evidence_source 记录补齐来源
5. 排序：score = w1·来源相关度 + w2·关键词覆盖 + w3·年份近因 + w4·引用规范化 + w5·综述加分
   **稳定排序**：同分时按来源进入顺序裁决，因此 source_priority 能影响 top-k 保留结果
6. 截断 top_k → 落库 → 抽取 → 返回
```

失败聚合：任一来源 4xx/5xx/超时/限流记入 `source_errors[{source, keyword, status, detail}]`，
整体仍返回成功部分；前端渲染为可见告警条 + 重试按钮。

## 5. 抽取设计（确定性、零模型）

`extract.py` 将摘要切句，按**线索词类别**匹配，命中句子作为 `evidence_span` 逐字保留。
10 个字段各有中英文线索词；未命中 → `value=None, evidence_source="none",
extraction_method="heuristic", evidence_status="unknown"`。

`classify.py` 的方法分类是**有序的**：
survey/review → benchmark/evaluation → security/robustness → skill/experience learning →
memory-augmented agent → retrieval-augmented generation → …
标题或摘要中出现 "benchmark" 会优先于 memory/RAG 线索，这是有意为之的确定性规则。

定位是**证据导航**而非学术结论：挑出最相关句子并保留原文，让研究者判断该行是否值得细读。

## 6. LLM 增强（默认关闭；未配置即 `LLM_NOT_CONFIGURED`）

Paper 字段抽取**始终是确定性的**：`EXTRACTION_MODE = "heuristic"`，`extract.py` 的结果
不会被任何模型输出覆盖或回写。LLM 只出现在两条受控路径上。

### 6.1 多智能体 Gap Pipeline

`services/llm.py`（唯一 Provider）+ `gap_agents.py`（角色 prompt 与逐字校验）+
`gap_pipeline.py`（七阶段编排）+ `gap_validator.py`（纯 Python 验证与门禁）。

```
planner → selection(Python) → literature_analysis → gap_analysis
        → gap_critic → counter_evidence → validation(Python)
```

- **Evidence Card**：Literature Analyst 每篇产出七字段卡片，单独存于 `evidence_cards`，
  **不回写 Paper 字段**。`evidence_source` 固定 `abstract`——只有摘要时系统不声称读过全文。
- **逐字校验**：每个 claim 的 `evidence_span` 必须能在**实际送入模型的摘要**中定位
  （容忍 whitespace 重排，定位后存原文片段）；定位失败 → 丢弃并记入 `rejected_fields`，
  绝不作为事实入库。无摘要的论文直接拒绝产卡，不触达模型。
- **Critic 隔离**：只看到 claim 与引用证据，看不到 Gap Agent 的推理；四项评分是 0~5 整数，
  风险是 LOW/MEDIUM/HIGH，**不输出百分比或伪精度概率**。
- **独立门禁**：`gap_validator.py` 重新核对论文是否真实存在、证据引用是否可核验、是否重复计数
  （含跨来源同 DOI）、DOI 是否规范、反证检索是否完成、prior art 碰撞、novelty/contradiction
  风险与 Critic 阈值。命中高度相关 prior art → `novelty_risk = HIGH` 并列出 `potential_prior_art`，
  不会直接 Accepted。最终状态只有 `accepted / needs_human_review / rejected`；
  通过门禁只表示"在当前检索范围内达到配置阈值"，**不是创新性的数学证明**。
- **反证检索**复用既有 `gap.py` 的真实三来源检索；`COUNTER_SEARCH_FAILED` 与
  `NO_COUNTER_EVIDENCE_FOUND` 严格区分，检索失败不能替空白"洗白"。

### 6.2 技能变异提议器

`services/evolution.py: llm_proposal`：每轮**最多 1 次**调用，Pydantic 校验，
未配置/超限额/失败/与父版本相同 → 回退确定性提议并写明 `llm_skip_reason`。

### 6.3 强制约束

- Key 只来自服务端环境变量（`RLE_LLM_ENABLED` / `RLE_LLM_API_KEY` / `RLE_LLM_BASE_URL` /
  `RLE_LLM_MODEL`），**不进数据库、日志、前端、Git**；异常文本在落盘前做 redaction。
- 每次调用都审计：agent_role、provider、model、request_id、时间、latency、成功/失败、
  token（若 provider 返回）、prompt hash、response hash；**不保存 prompt 正文**。
- 预算：`RLE_LLM_MAX_CALLS` 总额 + 每角色上限（planner 2 / analyst 30 / gap analyst 2 /
  critic 5 / counter query 5）。角色预算按**安装全局**计数，因此一轮真实管线跑完后，
  第二条真实管线需要先调高对应角色上限（本轮的 18 步 Workflow 真实链路即因此 NOT RUN）。
  真实调用（含 failed 与 output_rejected）计数，缓存命中免费；
  超预算 → 停止并置 `awaiting_budget`，已完成产物保留，resume 不重复付费。
- 缓存键 = role + model + prompt_version + prompt hash；schema 校验失败的回复**不入缓存**。
- 未配置 → `LLM_NOT_CONFIGURED`，不产生任何伪造 LLM 结果；18 步 Workflow 回退到确定性
  Gap 比较器并记录 `fallback_reason`。
- `FakeLLMProvider` 只用于 unit / integration tests，绝不写入真实 run / experiment / promotion 证据。

## 7. 实验与评测（独立、可复现）

### 7.1 冻结协议

`ExperimentSpec` 冻结：cases、sources、year_from/to、top_k、max_api_requests、use_cache、
baseline_version_id、candidate_version_id。两臂**共用同一协议**，只有查询计划不同。

- `_arms_must_differ` 校验器拒绝 baseline == candidate。
- `order_sources`：策略只能**置换**冻结来源集合的顺序，绝不增删来源。
- `effective_years`：策略只能**收窄**冻结年份窗口（下界取 max、上界取 min），不能放宽。
- `_allowed_queries`：查询计划按 `max_api_requests // len(sources)` 截断，
  截断事实作为一条 `source="budget"` 的记录写入 `source_errors`，不静默丢弃。

### 7.2 独立 Evaluator

纯 Python，不依赖 Agent 自我评价。指标：
Reference Coverage@K、Missed References、API Query Count、Unique Paper Count、Execution Time。

- 覆盖率针对**人工确认的参考集合**，不是领域绝对 Recall。
- **缓存不隐藏成本**：`total_api_queries = api_request_count + cache_hits`，
  请求比与 1.5× 上限检查都用这个总数。
- 记录 `reference_fingerprint`、`dataset_fingerprint`、`evaluator_version`、`computed_at`。
- `POST /api/experiments/verify` 从**原始快照**重算并与已存结果比对，返回 `matches_stored`
  与 `recomputed_from`；快照缺失时回退到已存记录并如实命名来源。

### 7.3 六条晋升门禁

1. Validation 覆盖率必须提升
2. Holdout 不得回退
3. API 请求 ≤ 1.5× Baseline（含缓存命中）
4. 无未处理的 API 错误
5. 评测数据指纹与评分器指纹必须匹配
6. 没有可靠参考集合不得晋升

此外还需要：候选已锁定、holdout 已执行、两臂都已执行。
Holdout 是**一次性终检**：候选锁定后才开放，且同一 spec 只允许搜索一次。
不满足则保持原 Active Skill，拒绝原因逐条返回。

## 8. 进化引擎

- **经验收集**：从已落库 ExperimentRun + 原始快照还原真实试验信号。
  `reference_titles` / `reference_years` **只对 development split 暴露**，防止泄漏。
- **6 类失败诊断**：Query Too Narrow、Missing Synonym、Wrong Research Terminology、
  Source Coverage Insufficient、Time Filter Too Restrictive、API Failure。
  每条附触发它的真实数字；无信号则不产生诊断；API 传输失败不归咎于 prompt；
  预算截断不算 API 失败。来源计数用 `Counter({s: 0 for s in spec.sources})`  seeding，
  静默来源因此可见（实测 arXiv 常为 0）。
- **CandidateProposer**：默认确定性，可选限额 LLM；每轮**最多 3 个候选**；
  只使用 development 试验；记录父版本 / 变异描述 / 来源试验 / 改动组件 / 创建时间。
- **预算推导**：`affordable_budget(baseline_requests, source_count, ceiling)` →
  `affordable = max(sources, min(int(baseline*1.5), ceiling))`，`queries = max(1, affordable//sources)`。
  基线为 0（尚无试验）且 3 来源 / 上限 6 时 → 3 请求 / 1 查询，
  因此只能把词**替换**进单模板，而不是加第二条查询。
- **缺证据就拒绝编造**：无确认参考集时拒绝 `reference_grounded_reformulation`；
  主题词已全部出现在已执行查询中时拒绝 `topic_coverage_reformulation`；
  来源优先级已等于实测贡献顺序时拒绝无意义重排。每条拒绝都写明原因。
- 需要改动冻结协议的诊断**只报告、不产生候选**。

## 9. 18 步 Workflow 编排器

```
research_topic → search_planning → literature_discovery → paper_extraction →
literature_matrix → gap_discovery → counter_evidence_search → human_approval* →
hypothesis → experiment_spec → baseline_execution → candidate_execution →
independent_evaluation → failure_diagnosis → skill_mutation → replay_evaluation →
promotion_decision* → research_dossier
```
`*` = 人工门禁（`HUMAN_STEPS`）。

设计要点：
- `STEP_SEQUENCE` 固定顺序，模型校验器拒绝乱序或缺步的状态。
- 每步调用**已拥有该能力的真实服务**，把实际产出的 id 与数字写进 `step.inputs/outputs`。
- 每次状态转移后 upsert 落盘 → 崩溃或重启后从准确的 pending 步继续。
- `advance(max_steps, from_step)`：`max_steps` 1..18，遇人工门禁或失败立即停止。
- 失败保留真实异常文本（`f"{type(exc).__name__}: {exc}"`），可原地重试（`attempts` 递增）。
- `_rewind` 清空该步及其后所有步骤的输出**与它们拥有的 context 键**
  （`STEP_CONTEXT_KEYS`），避免重跑时静默复用过期的人工批准。
- 已打开过 holdout 的流程**拒绝回退**。
- 跨流程批准被拒绝：只能批准本流程 `context["gap_ids"]` 中的 gap。
- **鸡生蛋问题**：spec 需要两个不同的臂，而提议器需要已执行的试验。
  解法是 `_gap_seed_candidate`——以被接受空白的支撑论文标题词频产生首个候选，
  复用与提议器相同的预算推导与单模板替换。替换词必须**同时**不在空白问题与该 case 的
  topic/query 措辞中，否则不做无意义变异；无新词时回退并明写"可能检索到与基线相同的论文"。
- 基准 case 由真实方法类派生出 3 个**不同**子主题，`assign_splits` 因此产出全部三个 split。
  参考 DOI 经真实 `verify_doi` 核验；全部核验失败则拒绝建基准。
  **派生参考的自指风险在 case notes 与步骤输出中原文披露**。
- 只跑 development / validation（`SEARCHABLE_SPLITS`），**holdout 在结构上不可由 workflow 打开**。
- 回放为每个新候选创建**新的冻结协议**（`created_by="workflow-replay"`），
  基线、参考集合、来源、年份、Top-K、上限与评分公式完全不变。
- 晋升被拒是**被记录的结果**（`outcome="refused"` + 全部原因）而非杀死流程的异常，
  档案因此能如实写出 `acceptance_status`。
- **LLM 以可恢复子阶段接入，18 个 step id 与既有确定性服务一个都没删**：
  第 2 步创建 `gap_pipeline` 并跑 planner（planner 查询最多取 2 条并入第 3 步真实检索）；
  第 4 步在启发式抽取审计之外附加 Evidence Card 统计；第 6 步推进到 `gap_critic`，
  优先使用 pipeline 已落盘的空白（`discovery_mode="llm_pipeline"`），
  未配置 / 无候选 / 候选无法投影时回退确定性比较器并写明 `fallback_reason`；
  第 7 步推进到 `validation`，只对仍为 `NOT_RUN` 的空白跑反证检索。
- 每个 LLM 阶段的产物都落盘，`advance` 遇 `awaiting_budget` 与 `awaiting_human` 一样立即停止；
  预算耗尽或 provider 未配置**不计入阶段重试次数**，修好后 resume 不会撞上重试上限，
  也不会把前面已付费的调用重跑一遍。planner 失败被标 `skipped`，检索照常进行。
- 第 18 步档案新增 `llm` 块：configured/status/provider/model/预算与用量/各角色用量/
  失败数/token/卡片数/审计入口，以及每条空白的 `discovery_mode`、`counter_status`、
  `novelty_risk`、`gate_status`、`validation_passed`。

## 10. API 设计

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 连通性自检（可选 `probe=1` 真实探测） |
| POST | `/api/literature/search` | 检索并落库，返回 run_id + papers + source_errors |
| GET | `/api/literature/runs` | 检索历史 |
| GET | `/api/literature/papers` | Library 列表，支持 year/source/review/evidence_status/query 过滤与分页 |
| GET | `/api/literature/papers/{id}` | 单篇详情含证据 |
| PATCH | `/api/literature/papers/{id}/fields/{field}` | 人工补充字段 → `evidence_source=manual` |
| POST | `/api/literature/matrix` | 由 paper_ids 生成对比矩阵 |
| GET | `/api/literature/matrix/export?format=csv\|json` | 导出 |
| POST | `/api/literature/report` | 生成 7 节研究报告 |
| POST | `/api/gaps/discover` | 多论文比较发现空白 + 可选反证检索 |
| GET | `/api/gaps` · `/api/gaps/{id}` | 列表 / 详情（含 reviews） |
| PATCH | `/api/gaps/{id}` | 人工接受 / 拒绝 / 编辑 |
| POST | `/api/gaps/{id}/counter-search` | 重跑三源反证检索 |
| POST | `/api/gap-pipeline/start` · `/{id}/advance` | 启动 / 有界推进七阶段（`max_stages` 1..7，可 `from_stage`） |
| GET | `/api/gap-pipeline` · `/{id}` | 列表（可按 workflow 过滤）/ 详情（含卡片、空白、审计与用量） |
| GET | `/api/llm/status` · `/api/llm/calls` | 配置与预算状态 / 调用审计（只有 hash 与计量） |
| GET | `/api/experiments/templates` | 唯一模板：Agent 进化相关假设 |
| GET/POST | `/api/experiments/benchmark/cases` | 基准列表 / 新建（真实 DOI 核验） |
| POST | `/api/experiments/benchmark/cases/{id}/references` · `/confirm` | 追加 / 人工确认参考 |
| POST | `/api/experiments/benchmark/assign-splits` | 按主题分组切分 |
| POST | `/api/experiments/design` · `/run` · `/verify` | 冻结协议 / 执行两臂 / 独立重算 |
| GET | `/api/experiments/specs` · `/specs/{id}` · `/runs` · `/runs/{id}` · `/compare/{spec}` | 查询与对比 |
| POST | `/api/experiments/specs/{id}/lock` | 锁定候选（holdout 前置条件） |
| GET | `/api/skills/versions` · `/active` · `/versions/{id}` · `/events` · `/history` | 版本注册表 |
| POST | `/api/skills/versions` · `/preview` · `/evaluate` · `/promote` · `/rollback` | 创建 / 预览查询 / 评测 / 晋升 / 回滚 |
| GET | `/api/evolve/failure-types` · `/rounds` · `/rounds/{id}` | 诊断目录与轮次 |
| POST | `/api/evolve/skills` | 真实进化轮（≤3 候选） |
| GET | `/api/workflows/steps` | 18 步目录（**必须先于 `/{id}` 声明**） |
| POST/GET | `/api/workflows` | 创建（只建状态）/ 列表 |
| GET | `/api/workflows/{id}` · `/{id}/dossier` | 状态 / 档案（未跑到第 18 步返回 409） |
| POST | `/api/workflows/{id}/advance` · `/approval` · `/decision` | 有界推进 / 空白批准 / 晋升决策 |

**没有任何 501 占位接口**。约定：列表响应带 `notice` 声明边界；
错误响应保留结构化 `reasons`，前端 `describeError` 逐条展示而不丢弃。

## 11. 前端架构

- 路由：`react-router-dom` 7，**11 个真实页面**共用同一侧边导航，无占位页。
- 状态：无 Redux；每页局部 `useState` + 统一 `guard()` 包装（busy / error / message），
  错误态真实展示服务端 `detail` 与逐条 `reasons`。
- 类型：`src/types/{paper,gap,gapPipeline,experiment,evolution,workflow}.ts` 与后端 Pydantic 模型手工对齐。
  `StepOutputs` 是**全可选的扁平接口**（各步写入的键互不冲突）。
- Research Gap 页展示**完整证据链**而非一个分数：`components/gap/EvidenceChain.tsx`
  按 ① LLM 候选 ② Critic 评分 ③ Python 验证 ④ 反证与 prior art ⑤ 最终门禁 五段展开，
  规则式空白显式标注"无 LLM 链"；`EvidenceCards.tsx` 展示逐字 span、`evidence_source=abstract`
  与被拒字段；`PipelinePanel.tsx` 展示 provider/预算/各角色用量、七阶段状态、Resume 与审计。
- 图表：Recharts 用于既有页面的年份分布与来源占比；
  **新增页面（Workflow / Dossier）一律用按真实数值比例绘制的 CSS 条 + 表格**，
  因为应用内浏览器视口塌陷（`innerWidth === 0`）导致 `ResponsiveContainer` 不挂载 SVG surface。
  覆盖率为 `null` 时显示 `—`，绝不显示 0。
- 开发代理：`vite.config.ts` 将 `/api` 代理到 `:8000`。
- 合规：前端代码内不出现任何 key；来源 API 均由后端调用。
- 构建：`tsc -b && vite build`，开启 `noUnusedLocals` / `noUnusedParameters` / `verbatimModuleSyntax`。

## 12. 非功能性设计

| 维度 | 做法 |
| --- | --- |
| 超时 | 每请求 20s；arXiv 单次 15s |
| 限速 | 每来源令牌桶：OpenAlex 8/s、Crossref 4/s、arXiv 0.3/s（≥3s 间隔）；桶容量至少 1 个整令牌，否则低于 1/s 的速率永远发不出请求 |
| 重试 | 仅对 429/5xx/网络错误，最多 2 次，退避 1s/3s，尊重 `Retry-After`（上限 10s）；4xx 不重试 |
| 代理 | `build_proxy_mounts()` 逐条校验 NO_PROXY（含 IPv6 字面量、CIDR、localhost），非法条目丢弃并记录，避免一个坏条目让三个来源同时 `InvalidURL` |
| 缓存 | 文件 JSON 缓存，key=规范化 URL，默认 TTL 24h，可 `refresh=1` 绕过；**成本统计包含缓存命中** |
| 礼貌池 | `mailto` 参数注入 OpenAlex/Crossref 请求 |
| 可观测 | 每 run 记录耗时、缓存命中、来源错误；实验保留原始响应快照；日志仅 stdout |
| 隐私 | 只存书目元数据与公开摘要，不存用户身份信息 |
| 测试 | **304 个离线测试通过 + 3 个 live 测试默认跳过**（patch 在使用点，不联网；autouse fixture 剥离本地 `.env` 的 LLM/gate 配置，保证离线套件不受真实凭据影响）；live 测试需 `RLE_LIVE_TESTS=1`，强制 `refresh=True`，autouse fixture 在本 loop 上关闭共享客户端 |
| LLM 可观测 | 每次调用一行审计（hash + 计量 + 状态），预算与缓存命中分开计数；未配置时显式 `LLM_NOT_CONFIGURED`，不伪造结果 |

## 13. 尚未完成 / 演进路径

| 项 | 状态 | 触发条件 |
| --- | --- | --- |
| 人工确认参考集合 | ⬜ **待人工标注** | 需要独立来源的参考 DOI，剔除派生重叠与 Crossref 组件记录 |
| 锁定候选 → holdout 终检 → 真实晋升 | ⬜ 仅有离线测试覆盖 | 参考集合确认后在 Experiment Lab 中人工完成 |
| 成功回滚的真实演示 | ⬜ 真实库中无 archived 版本 | 先有一次真实晋升 |
| LLM 真实 Provider 运行（Gap Pipeline） | ✅ **REAL**（2026-11-18）：DeepSeek `deepseek-flash`，7 阶段全部 completed；34/60 次调用、104,511 tokens、1 次 schema 拒绝未缓存 | 模型名以 `GET /models` 实测为准（该账号为 `deepseek-flash` / `deepseek-v4-pro`，无 `deepseek-chat`） |
| 真实 LLM E2E 的 20+ 论文规模 | ✅ **REAL**：30 篇检索（29 篇有摘要，2023–2026）、20 张 Evidence Card、5 条候选 Gap | OpenAlex 一次查询 HTTP 429 已如实记录为 source error；Crossref/arXiv 该组查询贡献 0 篇 |
| LLM 证据链 UI 的真实数据渲染 | ✅ **REAL**：浏览器核对 5 条真实 Gap 的五段证据链与 Dossier 旧档案回退 | 旧档案缺 `llm` 块曾导致页面崩溃，已修复并复核 |
| 18 步 Workflow 的真实 LLM 全链路 + 真实人工确认 | ⬜ **NOT RUN**：角色预算用尽（planner 2/2、gap 2/2、critic 5/5、counter 5/5，总额 34/60）；5 条 Gap 等人工决定 | 调高对应角色上限或换一次预算授权后，从 `human_approval` 起接续；不代签、不伪造 |
| Gap 提出依据单独落库（`novelty_rationale`） | ✅ 已完成：真实运行暴露 `novelty_risk` 枚举被写入 prose 导致拒绝，新增字段 + 严格校验回归测试 | —— |
| 正式部署 | ⬜ 本轮不做 | 前端可静态托管；后端需另行确认低成本常驻方案（Sites 无常驻 Python 运行时） |
| `run_papers` 关联表 | ⬜ 已定位根因，未修 | `papers` upsert 覆盖 `run_id`，跨 run 共享论文按 run 过滤会少显示；workflow context 不受影响 |