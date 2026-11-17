# ARCHITECTURE — ResearchLoop Evo

版本：v0.1（Phase 1）　日期：2026-11-17

## 1. 能力核实结论（决定架构的前置事实）

核实方式：官方文档 + 本机 HTTP 实测。**未启动 Cloud Agent，未部署，未产生额外额度消耗。**

| 能力 | 核实结果 | 对架构的影响 |
| --- | --- | --- |
| Qoder Sites | 个人付费档（含 Pro）可用；提供站点产物 + Database + Storage + Secrets + Function，站点可调用 Cloud Agents；Free 仅静态 | 前端可托管；**但没有自由常驻 Python 运行时**，FastAPI 后端不能作为长期在线服务部署在 Sites |
| Sites Database / Storage | 付费档可用，本期未启用 | Phase 2 若需跨设备共享研究项目再启用 |
| Sites 免费期 | 官方标注"上线限免，有使用上限，超限会临时限制创建/访问" | 不作为核心依赖，正式部署推迟到用户确认 |
| Cloud Agents | 可用；Session 状态机 `idle/running/rescheduling/terminated`；SSE 支持 `Last-Event-ID` 续传；**沙箱按 running 秒计费**（2026-08-10 起），模型调用按 token 折算；个人 PAT 官方标注仅适合测试/PoC | Phase 1 不使用；Phase 3（真实实验执行）是它的合理场景，届时需单独申请额度确认 |
| Credits 规则 | Pro 2000/月，当期清零不结转；失败请求不扣费；**Efficient 档限时 0.0x（付费用户选择即不扣 Credits）**；Credit Pack $20/1500、有效期 1 个月 | 见 `CREDIT_BUDGET.md` 的开发策略 |
| OpenAlex | 本机实测 HTTP 200，~1.7s；`abstract_inverted_index` 部分记录缺失 | 主力来源：元数据 + 摘要 |
| Crossref | 本机实测 HTTP 200；`/works` 结果默认不含 `abstract` | 补充 DOI/元数据校验与二次来源 |
| arXiv | 本机实测 `429 Rate exceeded`（需 ≥3s 间隔） | 可选来源，默认开启但严格限速 + 失败降级 |
| 学术出版商全文 | 未抓取 | 合规红线：不绕过付费墙，`fulltext` 证据只允许人工录入 |

## 2. 总体架构

```
┌──────────────── Browser (React SPA, :5173) ────────────────┐
│ Dashboard · Discovery · Library · Matrix · Report · 占位模块 │
└──────────────────────────┬─────────────────────────────────┘
                           │ REST/JSON (Vite dev proxy → :8000)
┌──────────────────────────▼─────────────────────────────────┐
│            FastAPI 后端 (Python 3.13, 本地运行)             │
│                                                            │
│  api/routes_literature   参数校验 · 运行记录 · 错误聚合     │
│  services/pipeline       多关键词×多来源编排                │
│    ├─ sources/openalex   ├─ sources/crossref  ─ arxiv      │
│    ├─ http.py            限速令牌桶 + 有界重试 + 文件缓存   │
│    ├─ normalize.py       RawRecord → Paper (+provenance)   │
│    ├─ dedupe.py          DOI 归一 · 标题相似度合并          │
│    ├─ rank.py            相关性 + 综述优先 + 年份衰减       │
│    ├─ extract.py         摘要证据化启发式抽取               │
│    ├─ report.py          事实/作者观点/系统推断分离         │
│    └─ export.py          CSV / JSON                        │
│  storage/store.py        SQLite: projects/runs/papers/edits│
│  services/llm.py         可选抽取器，默认 disabled          │
└──────────────────────────┬─────────────────────────────────┘
                           │ HTTPS
              OpenAlex · Crossref · arXiv（公开学术 API）
```

Phase 1 **没有** LLM 依赖：抽取、排序、报告都是确定性代码，可单测、可复现、零额度消耗。

## 3. 数据模型

### 3.1 FieldEvidence（证据单元，Phase 1 的核心设计）

```python
class FieldEvidence(BaseModel):
    value: str | list[str] | None = None
    evidence_source: Literal["abstract", "fulltext", "manual", "model_inference", "none"]
    evidence_span: str | None = None    # 支撑该字段的原文片段（逐字摘录）
    source_url: str | None = None       # 片段来自哪个可访问记录页
    confidence: Literal["high", "medium", "low", "unknown"]
    updated_at: str | None = None
```

规则：
- `value is not None` 但 `evidence_span is None` → 校验失败（Pydantic model_validator）。**这是"不许假装读过"的技术强制。**
- `evidence_source == "none"` 时 value 必须为 None。
- `fulltext` / `manual` 只能由用户编辑写入（API 层拒绝外部来源提交 `fulltext`）。

### 3.2 Paper

```python
class Paper(BaseModel):
    paper_id: str                    # openalex:<id> / crossref:<doi> / arxiv:<id>
    title: str
    authors: list[str]
    publication_year: int | None
    venue: str | None
    doi: str | None                  # 归一化为 10.xxxx/xxxx
    abstract: str | None
    research_problem: FieldEvidence
    method: FieldEvidence
    dataset: FieldEvidence
    evaluation_metrics: FieldEvidence
    findings: FieldEvidence
    limitations: FieldEvidence
    future_work: FieldEvidence
    source: Literal["openalex", "crossref", "arxiv"]
    source_url: str                  # 原始记录页，可点击核验
    oa_url: str | None
    document_type: str | None
    is_review: bool
    citation_count: int | None
    relevance_score: float
    evidence_status: Literal["metadata_only", "abstract_grounded", "fulltext_grounded", "partially_missing", "unknown"]
    missing_fields: list[str]        # 由 evidence 自动推导，不手填
    duplicate_of: str | None         # 被合并到的 paper_id
    language: str | None
    retrieved_at: str
    run_id: str | None
```

`evidence_status` 语义：
- `metadata_only`：只有书目信息，无摘要 → 抽取字段全 `unknown`。
- `abstract_grounded`：抽取字段来自摘要，未见全文。
- `partially_missing`：部分字段有证据、部分为 unknown。
- `fulltext_grounded`：仅当人工/合法开放全文证据录入后才允许。

### 3.3 SQLite 表

```
projects(id, topic, field, created_at, updated_at)
runs(id, project_id, request_json, created_at, finished_at, status, source_errors_json, paper_count)
papers(paper_id, run_id, project_id, year, doi, source, is_review, evidence_status, json, retrieved_at)
paper_edits(paper_id, field, value_json, evidence_source, evidence_span, updated_at)  -- 人工补充/矩阵编辑
cache(key, url, payload, fetched_at, ttl_seconds)  -- 也在文件缓存中，DB 仅可选
```

索引：`papers(run_id)`、`papers(doi)`、`papers(publication_year)`、`paper_edits(paper_id)`。

## 4. 检索与去重流程

```
1. 关键词集合 = 用户关键词 ∪ 主题切分扩展（标注 origin="system_expanded"）
2. 对 (keyword × source) 组合并发但有界（默认 max 6，每来源独立令牌桶）
3. 每个来源返回 RawRecord → normalize → Paper（含 source_url）
4. 去重：
   a. DOI 归一（去 https://doi.org/ 前缀、小写）→ 完全相同即合并，保留信息最全记录，其余 duplicate_of 指向
   b. 无 DOI 时标题归一（去标点/小写/去停用词）→ token 集合 Jaccard 与 SequenceMatcher 双指标，
      默认 jaccard ≥ 0.85 或 ratio ≥ 0.92 判为同一篇
   c. 合并时字段并集：摘要缺失方可用另一来源补齐，但 evidence_source 记录补齐来源
5. 排序：score = w1·来源相关度 + w2·关键词覆盖 + w3·年份近因 + w4·引用规范化 + w5·综述加分
6. 截断 top_k → 落库 → 抽取（extract.py）→ 返回
```

失败聚合：任一来源 4xx/5xx/超时/限流，记入 `source_errors[{source, keyword, status, detail}]`，整体仍返回成功部分；前端把该区块渲染为可见的告警条 + 重试按钮。

## 5. 抽取设计（Phase 1：确定性、零模型）

`extract.py` 将摘要切句，按**线索词类别**匹配，命中句子作为 `evidence_span` 逐字保留：

| 字段 | 线索（英文 + 中文） |
| --- | --- |
| research_problem | "problem", "challenge", "however", "existing approaches", "难以", "尚缺乏" |
| method | "we propose", "we present", "we develop", "our approach", "we design", "本文提出" |
| dataset | "dataset", "benchmark", "experiments on", "corpus", "we evaluate on", "数据集" |
| evaluation_metrics | "accuracy", "F1", "recall", "precision", "MRR", "recall rate", "指标" |
| findings | "results show", "outperform", "improve by", "achieves", "实验表明", "提升" |
| limitations | "limitation", "however", "still remains", "future", "cannot", "不足" |
| future_work | "future work", "remain", "further investigate", "展望" |

分类规则要求"提案线索"与"局限线索"在同一句冲突时按优先次序归一类并把冲突记入 `ambiguity_flags`，避免过度自信。
未命中 → `value=None, evidence_source="none", confidence="unknown"`。

这套抽取的定位是**证据导航**而不是学术结论：它把最相关句子挑出来并保留原文，让研究者快速判断该行是否值得细读。真正的高质量抽取留给 Phase 2 的可选 LLM 增强（默认关闭，见下）。

## 6. 可选 LLM 增强（默认关闭）

`app/services/llm.py` 定义 `EvidenceExtractor` 协议与两个实现：

- `HeuristicExtractor`（默认，零成本，离线）
- `RemoteLLMExtractor`（需在 `.env` 显式配置 `RLE_LLM_ENABLED=1` + provider 与 key）

强制约束：LLM 输出必须以输入摘要中的**逐字片段**为 evidence_span，span 不在原文中即被丢弃并记 `rejected_span`。开关关闭时任何请求都不会触达模型，保证 Phase 1 零额度。

## 7. API 设计

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 后端与各来源连通性自检（可选 `probe=1` 真实探测） |
| POST | `/api/literature/search` | 检索并落库，返回 run_id + papers + source_errors |
| GET | `/api/literature/runs` | 检索历史 |
| GET | `/api/literature/papers` | Library 列表，支持 year/source/review/evidence_status/query 过滤与分页 |
| GET | `/api/literature/papers/{paper_id}` | 单篇详情含证据 |
| PATCH | `/api/literature/papers/{paper_id}/fields/{field}` | 人工补充字段 → `evidence_source=manual` |
| POST | `/api/literature/matrix` | 由 paper_ids 生成对比矩阵 |
| GET | `/api/literature/matrix/export?format=csv\|json` | 导出 |
| POST | `/api/literature/report` | 生成文献研究报告 |
| ANY | `/api/gaps/*` `/api/experiments/*` `/api/evolve/*` `/api/skills/*` | `501` + `{phase, reason, status:"not_implemented"}` |

约定：所有列表响应带 `meta{retrieved_at, cache_hits, source_errors, notice}`；`notice` 用于声明"仅摘要证据，未读全文"这类边界。

## 8. 前端架构

- 路由：`react-router-dom`，五实页 + 四占位页共用同一侧边导航（占位页灰标 + "Phase N"）。
- 状态：无 Redux；每页一个 `useAsync` hook（loading / error / data / retry），错误态真实展示 `detail`。
- 类型：`src/types/paper.ts` 与后端 Pydantic 模型手工对齐（字段名一致，注释标明）。
- 图表：Recharts 用于年份分布柱图与来源占比条图，数据源是当前 run 的真实论文。
- 开发代理：`vite.config.ts` 将 `/api` 代理到 `:8000`，生产构建后由用户自定部署方式。
- 合规：前端代码内不出现任何 key；来源 API 均由后端调用。

## 9. 非功能性设计

| 维度 | 做法 |
| --- | --- |
| 超时 | 每请求 20s；arXiv 单次 15s |
| 限速 | 每来源令牌桶：OpenAlex 8/s、Crossref 4/s、arXiv 0.3/s（≥3s 间隔） |
| 重试 | 仅对 429/5xx/网络错误，最多 2 次，指数退避 1s/3s；4xx 不重试 |
| 缓存 | 文件 JSON 缓存，key=规范化 URL，默认 TTL 24h，可 `?refresh=1` 绕过 |
| 礼貌池 | `mailto` 参数注入 OpenAlex/Crossref 请求 |
| 可观测 | 每个 run 记录耗时、缓存命中、来源错误；日志仅 stdout |
| 隐私 | 只存书目元数据与公开摘要，不存用户身份信息 |
| 测试 | 离线单测（fixture，不联网）+ 可选真实 API 冒烟测试（需环境变量显式开启） |

## 10. 演进路径

| Phase | 架构增量 | 触发条件 |
| --- | --- | --- |
| 2 Research Gap | `gap/` 服务：从 limitations/future_work 证据聚类出候选空白 + 证据链打分；可选 LLM | Phase 1 抽检通过 |
| 3 Experiment Lab | 实验 spec（可复现代码 + 种子 + 数据）与执行沙箱；若本地算力不足，评估 Cloud Agent（需额度确认） | 空白列表可用 |
| 4 Evolution Lab | 轨迹存储、Skill 文本变体搜索与反思闭环 | 有真实失败轨迹 |
| 5 Skill Registry | 版本化 Skill + 独立评测集 + 晋升门禁（held-out，未达标不覆盖） | Phase 4 产物稳定 |
| 部署 | 前端静态托管（Sites 或其他），后端 API 需另行确认低成本方案 | 用户明确要求上线 |
